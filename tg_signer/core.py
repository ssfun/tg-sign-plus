import asyncio
import json
import logging
import os
import pathlib
import random
import sqlite3
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from datetime import time as dt_time
from typing import Generic, List, Optional, Type, TypeVar, Union
from urllib import parse

import httpx
from croniter import CroniterBadCronError, croniter
from pydantic import BaseModel, ValidationError
from pyrogram import Client as BaseClient
from pyrogram import errors, filters, raw
from pyrogram.enums import ChatMembersFilter
from pyrogram.handlers import EditedMessageHandler, MessageHandler
from pyrogram.methods.utilities.idle import idle
from pyrogram.types import Message, Object, User

from tg_signer.config import (
    ActionT,
    AssertSuccessByTextAction,
    BaseJSONConfig,
    ChooseOptionByImageAction,
    ClickButtonByCalculationProblemAction,
    ClickButtonByPoetryFillAction,
    ClickKeyboardByTextAction,
    HttpCallback,
    MatchConfig,
    MonitorConfig,
    ReplyByCalculationProblemAction,
    ReplyByImageRecognitionAction,
    SendDiceAction,
    SendTextAction,
    SignChatV3,
    SignConfigV3,
    SupportAction,
    UDPForward,
)

from .ai_actions import (
    choose_option_by_image,
    click_button_by_calculation_problem,
    click_button_by_poetry_fill,
    reply_by_calculation_problem,
    reply_by_image_recognition,
)
from .ai_tools import AITools, OpenAIConfigManager
from .callback_actions import request_callback_answer
from .client_manager import Client, close_client_by_name, get_api_config, get_client, get_proxy
from .keyboard_actions import click_keyboard_by_text
from .message_helpers import readable_chat, readable_message
from .message_receivers import handle_edited_message, handle_incoming_message, store_incoming_message
from .notification.server_chan import sc_send
from .scheduled_messages import get_scheduled_messages, schedule_messages
from .text_cleaners import clean_text_for_match, clean_text_for_send
from .utils import UserInput, print_to_user
from .wait_dispatcher import BusinessRetryableError, dispatch_action_on_message, wait_for_action

# Monkeypatch sqlite3.connect to increase default timeout
_original_sqlite3_connect = sqlite3.connect


def _patched_sqlite3_connect(*args, **kwargs):
    # Force timeout to be at least 10 seconds, even if Pyrogram sets it to 1
    if "timeout" in kwargs:
        if kwargs["timeout"] < 30:
            kwargs["timeout"] = 30
    else:
        kwargs["timeout"] = 30
    return _original_sqlite3_connect(*args, **kwargs)


sqlite3.connect = _patched_sqlite3_connect

# Monkeypatch pyrogram.Client.invoke to add backpressure and retry logic for updates
_original_invoke = BaseClient.invoke
_get_channel_diff_semaphore = asyncio.Semaphore(50)

async def _patched_invoke(self, query, *args, **kwargs):
    if isinstance(query, (raw.functions.updates.GetChannelDifference, raw.functions.updates.GetDifference)):
        # Disable Pyrogram's internal sleep and retry mechanisms to prevent blocking the semaphore indefinitely
        kwargs.setdefault("sleep_threshold", 0)
        kwargs["retries"] = 0
        kwargs.setdefault("timeout", 5.0)

        async with _get_channel_diff_semaphore:
            max_retries = 2
            base_delay = 1.0
            for attempt in range(max_retries + 1):
                try:
                    return await _original_invoke(self, query, *args, **kwargs)
                except Exception as e:
                    err_str = str(e).lower()
                    if isinstance(e, asyncio.TimeoutError) or "timeout" in err_str or "connection" in err_str or "flood" in err_str or "network" in err_str:
                        if attempt < max_retries:
                            delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                            if "flood" in err_str and hasattr(e, "value"):
                                delay = min(e.value, 3.0)  # Wait for a shorter time, max 3 seconds
                            await asyncio.sleep(delay)
                            continue

                        logger.warning(f"Drop updates for {type(query).__name__} due to error: {e}")

                        if isinstance(query, raw.functions.updates.GetChannelDifference):
                            from pyrogram.raw.types.updates import (
                                ChannelDifferenceEmpty,
                            )
                            return ChannelDifferenceEmpty(pts=query.pts, timeout=0, final=True)
                        elif isinstance(query, raw.functions.updates.GetDifference):
                            from pyrogram.raw.types.updates import DifferenceEmpty
                            return DifferenceEmpty(date=query.date, seq=query.pts)
                    raise
    return await _original_invoke(self, query, *args, **kwargs)

BaseClient.invoke = _patched_invoke

logger = logging.getLogger("tg-signer")

DICE_EMOJIS = ("🎲", "🎯", "🏀", "⚽", "🎳", "🎰")

OPENAI_USE_PROMPT = "当前任务需要配置大模型，请确保运行前正确设置`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`等环境变量，或通过`tg-signer llm-config`持久化配置。"

def get_now():
    tz_name = os.environ.get("TZ") or "Asia/Hong_Kong"
    try:
        return datetime.now(tz=ZoneInfo(tz_name))
    except Exception:
        return datetime.now(tz=ZoneInfo("UTC"))


def make_dirs(path: pathlib.Path, exist_ok=True):
    path = pathlib.Path(path)
    if not path.is_dir():
        os.makedirs(path, exist_ok=exist_ok)
    return path


ConfigT = TypeVar("ConfigT", bound=BaseJSONConfig)


class BaseUserWorker(Generic[ConfigT]):
    _workdir = "."
    _tasks_dir = "tasks"
    cfg_cls: Type["ConfigT"] = BaseJSONConfig

    def __init__(
        self,
        task_name: str = None,
        session_dir: str = ".",
        account: str = "my_account",
        proxy=None,
        workdir=None,
        session_string: str = None,
        in_memory: bool = False,
        api_id: int = None,
        api_hash: str = None,
        no_updates: Optional[bool] = None,
        *,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        self.task_name = task_name or "my_task"
        self._session_dir = pathlib.Path(session_dir)
        self._account = account
        self._proxy = proxy
        if workdir:
            self._workdir = pathlib.Path(workdir)
        client_kwargs = {
            "workdir": self._session_dir,
            "session_string": session_string,
            "in_memory": in_memory,
            "api_id": api_id,
            "api_hash": api_hash,
            "loop": loop,
        }
        if no_updates is not None:
            client_kwargs["no_updates"] = no_updates

        self.app = get_client(
            account,
            proxy,
            **client_kwargs,
        )
        self.loop = self.app.loop
        self.user: Optional[User] = None
        self._config = None
        self.context = self.ensure_ctx()

    def ensure_ctx(self):
        return {}

    def app_run(self, coroutine=None):
        if coroutine is not None:
            run = self.loop.run_until_complete
            run(coroutine)
        else:
            self.app.run()

    @property
    def workdir(self) -> pathlib.Path:
        workdir = self._workdir
        make_dirs(workdir)
        return pathlib.Path(workdir)

    @property
    def tasks_dir(self):
        tasks_dir = self.workdir / self._tasks_dir
        make_dirs(tasks_dir)
        return pathlib.Path(tasks_dir)

    @property
    def task_dir(self):
        task_dir = self.tasks_dir / self.task_name
        make_dirs(task_dir)
        return task_dir

    def get_user_dir(self, user: User):
        user_dir = self.workdir / "users" / str(user.id)
        make_dirs(user_dir)
        return user_dir

    @property
    def config_file(self):
        return self.task_dir.joinpath("config.json")

    @property
    def config(self) -> ConfigT:
        return self._config or self.load_config()

    @config.setter
    def config(self, value):
        self._config = value

    def log(self, msg, level: str = "INFO", **kwargs):
        msg = f"账户「{self._account}」- 任务「{self.task_name}」: {msg}"
        if level.upper() == "INFO":
            logger.info(msg, **kwargs)
        elif level.upper() == "WARNING":
            logger.warning(msg, **kwargs)
        elif level.upper() == "ERROR":
            logger.error(msg, **kwargs)
        elif level.upper() == "CRITICAL":
            logger.critical(msg, **kwargs)
        else:
            logger.debug(msg, **kwargs)

    def ask_for_config(self):
        raise NotImplementedError

    def write_config(self, config: BaseJSONConfig):
        with open(self.config_file, "w", encoding="utf-8") as fp:
            json.dump(config.to_jsonable(), fp, ensure_ascii=False)

    def reconfig(self):
        config = self.ask_for_config()
        self.write_config(config)
        return config

    def load_config(self, cfg_cls: Type[ConfigT] = None) -> ConfigT:
        cfg_cls = cfg_cls or self.cfg_cls
        if not self.config_file.exists():
            config = self.reconfig()
        else:
            with open(self.config_file, "r", encoding="utf-8") as fp:
                config, from_old = cfg_cls.load(json.load(fp))
                if from_old:
                    self.write_config(config)
        self.config = config
        return config

    def get_task_list(self):
        signs = []
        for d in os.listdir(self.tasks_dir):
            if self.tasks_dir.joinpath(d).is_dir():
                signs.append(d)
        return signs

    def list_(self):
        print_to_user("已配置的任务：")
        for d in self.get_task_list():
            print_to_user(d)

    def set_me(self, user: User):
        self.user = user
        with open(
            self.get_user_dir(user).joinpath("me.json"), "w", encoding="utf-8"
        ) as fp:
            fp.write(str(user))

    async def login(self, num_of_dialogs=20, print_chat=True):
        self.log("开始登录...")
        app = self.app
        async with app:
            me = await app.get_me()
            self.set_me(me)
            latest_chats = []
            try:
                async for dialog in app.get_dialogs(num_of_dialogs):
                    try:
                        chat = getattr(dialog, "chat", None)
                        if chat is None:
                            self.log("get_dialogs 返回空 chat，已跳过", level="WARNING")
                            continue
                        chat_id = getattr(chat, "id", None)
                        if chat_id is None:
                            self.log("get_dialogs 返回 chat.id 为空，已跳过", level="WARNING")
                            continue
                        latest_chats.append(
                            {
                                "id": chat_id,
                                "title": chat.title,
                                "type": chat.type,
                                "username": chat.username,
                                "first_name": chat.first_name,
                                "last_name": chat.last_name,
                            }
                        )
                        if print_chat:
                            print_to_user(readable_chat(chat))
                    except Exception as e:
                        self.log(
                            f"处理 dialog 失败，已跳过: {type(e).__name__}: {e}",
                            level="WARNING",
                        )
                        continue
            except Exception as e:
                self.log(
                    f"get_dialogs 中断，返回已获取结果: {type(e).__name__}: {e}",
                    level="WARNING",
                )

            with open(
                self.get_user_dir(me).joinpath("latest_chats.json"),
                "w",
                encoding="utf-8",
            ) as fp:
                json.dump(
                    latest_chats,
                    fp,
                    indent=4,
                    default=Object.default,
                    ensure_ascii=False,
                )

    async def logout(self):
        self.log("开始登出...")
        is_authorized = await self.app.connect()
        if not is_authorized:
            await self.app.storage.delete()
            return None
        return await self.app.log_out()

    async def send_message(
        self, chat_id: Union[int, str], text: str, delete_after: int = None, **kwargs
    ):
        """
        发送文本消息
        :param chat_id:
        :param text:
        :param delete_after: 秒, 发送消息后进行删除，``None`` 表示不删除, ``0`` 表示立即删除.
        :param kwargs:
        :return:
        """
        message = await self.app.send_message(chat_id, text, **kwargs)
        self.log(
            f"消息已发送: {text}",
            stage="action",
            event="message_sent",
            meta={"chat_id": chat_id, "message_id": getattr(message, 'id', None), "text": text},
        )
        if delete_after is not None:
            self.log(
                f"消息将在 {delete_after} 秒后删除",
                stage="action",
                event="message_delete_scheduled",
                meta={"chat_id": chat_id, "message_id": getattr(message, 'id', None), "delete_after": delete_after},
            )
            await asyncio.sleep(delete_after)
            await message.delete()
            self.log(
                "消息已删除",
                stage="action",
                event="message_deleted",
                meta={"chat_id": chat_id, "message_id": getattr(message, 'id', None)},
            )
        return message

    async def send_dice(
        self,
        chat_id: Union[int, str],
        emoji: str = "🎲",
        delete_after: int = None,
        **kwargs,
    ):
        """
        发送DICE类型消息
        :param chat_id:
        :param emoji: Should be one of "🎲", "🎯", "🏀", "⚽", "🎳", or "🎰".
        :param delete_after:
        :param kwargs:
        :return:
        """
        emoji = emoji.strip()
        if emoji not in DICE_EMOJIS:
            self.log(
                f"Warning, emoji should be one of {', '.join(DICE_EMOJIS)}",
                level="WARNING",
            )
        message = await self.app.send_dice(chat_id, emoji, **kwargs)
        if message:
            self.log(
                f"骰子已发送: {emoji}",
                stage="action",
                event="dice_sent",
                meta={"chat_id": chat_id, "message_id": getattr(message, 'id', None), "emoji": emoji},
            )
        if message and delete_after is not None:
            self.log(
                f"骰子将在 {delete_after} 秒后删除",
                stage="action",
                event="dice_delete_scheduled",
                meta={"chat_id": chat_id, "message_id": getattr(message, 'id', None), "delete_after": delete_after},
            )
            await asyncio.sleep(delete_after)
            try:
                await message.delete()
                self.log(
                    "骰子已删除",
                    stage="action",
                    event="dice_deleted",
                    meta={"chat_id": chat_id, "message_id": getattr(message, 'id', None)},
                )
            except Exception as e:
                self.log(
                    f"删除骰子消息失败: {e}",
                    level="ERROR",
                    stage="action",
                    event="dice_delete_failed",
                    meta={"chat_id": chat_id, "message_id": getattr(message, 'id', None), "error_type": type(e).__name__},
                )
        return message

    async def search_members(
        self, chat_id: Union[int, str], query: str, admin=False, limit=10
    ):
        filter_ = ChatMembersFilter.SEARCH
        if admin:
            filter_ = ChatMembersFilter.ADMINISTRATORS
            query = ""
        async for member in self.app.get_chat_members(
            chat_id, query, limit=limit, filter=filter_
        ):
            yield member

    async def list_members(
        self, chat_id: Union[int, str], query: str = "", admin=False, limit=10
    ):
        async with self.app:
            async for member in self.search_members(chat_id, query, admin, limit):
                print_to_user(
                    User(
                        id=member.user.id,
                        username=member.user.username,
                        first_name=member.user.first_name,
                        last_name=member.user.last_name,
                        is_bot=member.user.is_bot,
                    )
                )

    def export(self):
        with open(self.config_file, "r", encoding="utf-8") as fp:
            data = fp.read()
        return data

    def import_(self, config_str: str):
        with open(self.config_file, "w", encoding="utf-8") as fp:
            fp.write(config_str)

    def ask_one(self):
        raise NotImplementedError

    def ensure_ai_cfg(self):
        cfg_manager = OpenAIConfigManager(self.workdir)
        cfg = cfg_manager.load_config()
        if not cfg:
            cfg = cfg_manager.ask_for_config()
        return cfg

    def get_ai_tools(self):
        return AITools(self.ensure_ai_cfg())


class Waiter:
    def __init__(self):
        self.waiting_ids = set()
        self.waiting_counter = Counter()

    def add(self, elm):
        self.waiting_ids.add(elm)
        self.waiting_counter[elm] += 1

    def discard(self, elm):
        self.waiting_ids.discard(elm)
        self.waiting_counter.pop(elm, None)

    def sub(self, elm):
        self.waiting_counter[elm] -= 1
        if self.waiting_counter[elm] <= 0:
            self.discard(elm)

    def clear(self):
        self.waiting_ids.clear()
        self.waiting_counter.clear()

    def __bool__(self):
        return bool(self.waiting_ids)

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.waiting_counter}>"


class UserSignerWorkerContext(BaseModel):
    """签到工作上下文"""

    class Config:
        arbitrary_types_allowed = True

    waiter: Waiter
    sign_chats: dict  # 签到配置列表, int -> list[SignChatV3]
    chat_messages: dict  # 收到的消息, int -> dict[int, Optional[Message]]
    last_callback_texts: dict  # 最近一次按钮弹窗文案, int -> str
    waiting_message: Optional[Message] = None  # 正在处理的消息


class UserSigner(BaseUserWorker[SignConfigV3]):
    _workdir = ".signer"
    _tasks_dir = "signs"
    cfg_cls = SignConfigV3
    context: UserSignerWorkerContext

    def ensure_ctx(self) -> UserSignerWorkerContext:
        return UserSignerWorkerContext(
            waiter=Waiter(),
            sign_chats=defaultdict(list),
            chat_messages=defaultdict(dict),
            last_callback_texts={},
            waiting_message=None,
        )

    def _load_chat_cache(self) -> List[dict]:
        try:
            from backend.core.database import get_session_local
            from backend.models.account_chat_cache import AccountChatCacheItem

            db = get_session_local()()
            try:
                rows = (
                    db.query(AccountChatCacheItem)
                    .filter(AccountChatCacheItem.account_name == self._account)
                    .order_by(AccountChatCacheItem.title.asc(), AccountChatCacheItem.chat_id.asc())
                    .all()
                )
                return [
                    {
                        "id": int(row.chat_id),
                        "title": row.title,
                        "username": row.username,
                        "type": row.chat_type,
                        "first_name": row.first_name,
                    }
                    for row in rows
                ]
            finally:
                db.close()
        except Exception:
            return []

    def _find_cached_chat(self, chat_id: int, name: Optional[str]) -> Optional[dict]:
        entries = self._load_chat_cache()

        candidate_ids = {chat_id}
        if isinstance(chat_id, int):
            candidate_ids.add(-chat_id)
            try:
                candidate_ids.add(int(f"-100{abs(chat_id)}"))
            except Exception:
                pass

        def _search_entries(cache_entries: List[dict]) -> Optional[dict]:
            for entry in cache_entries:
                try:
                    if entry.get("id") in candidate_ids:
                        return entry
                except Exception:
                    continue
            if name:
                name_key = name.strip().lower().lstrip("@")
                for entry in cache_entries:
                    username = (entry.get("username") or "").strip().lower()
                    title = (entry.get("title") or "").strip().lower()
                    if username and username == name_key:
                        return entry
                    if title and title == name.strip().lower():
                        return entry
            return None

        # 1. Search current account cache
        found = _search_entries(entries)
        if found:
            return found

        # 2. Search all other accounts caches
        try:
            from backend.core.database import get_session_local
            from backend.models.account_chat_cache import AccountChatCacheItem

            db = get_session_local()()
            try:
                rows = (
                    db.query(AccountChatCacheItem)
                    .filter(AccountChatCacheItem.account_name != self._account)
                    .order_by(AccountChatCacheItem.account_name.asc(), AccountChatCacheItem.title.asc(), AccountChatCacheItem.chat_id.asc())
                    .all()
                )
                if rows:
                    other_entries = [
                        {
                            "id": int(row.chat_id),
                            "title": row.title,
                            "username": row.username,
                            "type": row.chat_type,
                            "first_name": row.first_name,
                        }
                        for row in rows
                    ]
                    found = _search_entries(other_entries)
                    if found:
                        return found
            finally:
                db.close()
        except Exception:
            pass

        return None

    @property
    def sign_record_file(self):
        sign_record_dir = self.task_dir / str(self.user.id)
        make_dirs(sign_record_dir)
        return sign_record_dir / "sign_record.json"

    def _ask_actions(
        self, input_: UserInput, available_actions: List[SupportAction] = None
    ) -> List[ActionT]:
        print_to_user(f"{input_.index_str}开始配置<动作>，请按照实际签到顺序配置。")
        available_actions = available_actions or list(SupportAction)
        actions = []
        while True:
            try:
                local_input_ = UserInput()
                print_to_user(f"第{len(actions) + 1}个动作: ")
                for action in available_actions:
                    print_to_user(f"  {action.value}: {action.desc}")
                print_to_user()
                action_str = local_input_("输入对应的数字选择动作: ").strip()
                action = SupportAction(int(action_str))
                if action not in available_actions:
                    raise ValueError(f"不支持的动作: {action}")
                if len(actions) == 0 and action not in [
                    SupportAction.SEND_TEXT,
                    SupportAction.SEND_DICE,
                ]:
                    raise ValueError(
                        f"第一个动作必须为「{SupportAction.SEND_TEXT.desc}」或「{SupportAction.SEND_DICE.desc}」"
                    )
                if action == SupportAction.SEND_TEXT:
                    text = local_input_("输入要发送的文本: ")
                    actions.append(SendTextAction(text=text))
                elif action == SupportAction.SEND_DICE:
                    dice = local_input_("输入要发送的骰子（如 🎲, 🎯）: ")
                    actions.append(SendDiceAction(dice=dice))
                elif action == SupportAction.CLICK_KEYBOARD_BY_TEXT:
                    text_of_btn_to_click = local_input_("键盘中需要点击的按钮文本: ")
                    actions.append(ClickKeyboardByTextAction(text=text_of_btn_to_click))
                elif action == SupportAction.CHOOSE_OPTION_BY_IMAGE:
                    print_to_user(
                        "图片识别将使用大模型回答，请确保大模型支持图片识别。"
                    )
                    actions.append(ChooseOptionByImageAction())
                elif action == SupportAction.REPLY_BY_CALCULATION_PROBLEM:
                    print_to_user("计算题将使用大模型回答。")
                    actions.append(ReplyByCalculationProblemAction())
                elif action == SupportAction.REPLY_BY_IMAGE_RECOGNITION:
                    print_to_user("AI will recognize text from image and send it automatically.")
                    actions.append(ReplyByImageRecognitionAction())
                elif action == SupportAction.CLICK_BUTTON_BY_CALCULATION_PROBLEM:
                    print_to_user("AI will calculate the answer and click the matching button.")
                    actions.append(ClickButtonByCalculationProblemAction())
                elif action == SupportAction.CLICK_BUTTON_BY_POETRY_FILL:
                    print_to_user("AI will infer the missing poetry character and click the matching button.")
                    actions.append(ClickButtonByPoetryFillAction())
                elif action == SupportAction.ASSERT_SUCCESS_BY_TEXT:
                    keywords_raw = local_input_("输入成功关键字，多个请用 # 分隔: ")
                    keywords = [item.strip() for item in keywords_raw.split("#") if item.strip()]
                    if not keywords:
                        raise ValueError("至少需要一个成功关键字")
                    actions.append(AssertSuccessByTextAction(keywords=keywords))
                else:
                    raise ValueError(f"不支持的动作: {action}")
                if local_input_("是否继续添加动作？(y/N)：").strip().lower() != "y":
                    break
            except (ValueError, ValidationError) as e:
                print_to_user("错误: ")
                print_to_user(e)
        input_.incr()
        return actions

    def ask_one(self) -> SignChatV3:
        input_ = UserInput(numbering_lang="chinese_simple")
        chat_id = int(input_("Chat ID（登录时最近对话输出中的ID）: "))
        name = input_("Chat名称（可选）: ")
        actions = self._ask_actions(input_)
        delete_after = (
            input_(
                "等待N秒后删除消息（发送消息后等待进行删除, '0'表示立即删除, 不需要删除直接回车）, N: "
            )
            or None
        )
        if delete_after:
            delete_after = int(delete_after)
        cfgs = {
            "chat_id": chat_id,
            "name": name,
            "delete_after": delete_after,
            "actions": actions,
        }
        return SignChatV3.parse_obj(cfgs)

    def ask_for_config(self) -> "SignConfigV3":
        chats = []
        i = 1
        print_to_user(f"开始配置任务<{self.task_name}>\n")
        while True:
            print_to_user(f"第{i}个任务: ")
            try:
                chat = self.ask_one()
                print_to_user(chat)
                print_to_user(f"第{i}个任务配置成功\n")
                chats.append(chat)
            except Exception as e:
                print_to_user(e)
                print_to_user("配置失败")
                i -= 1
            continue_ = input("继续配置任务？(y/N)：")
            if continue_.strip().lower() != "y":
                break
            i += 1
        sign_at_prompt = "签到时间（time或crontab表达式，如'06:00:00'或'0 6 * * *'）: "
        sign_at_str = input(sign_at_prompt) or "06:00:00"
        while not (sign_at := self._validate_sign_at(sign_at_str)):
            print_to_user("请输入正确的时间格式")
            sign_at_str = input(sign_at_prompt) or "06:00:00"

        random_seconds_str = input("签到时间误差随机秒数（默认为0）: ") or "0"
        random_seconds = int(float(random_seconds_str))
        config = SignConfigV3.parse_obj(
            {
                "chats": chats,
                "sign_at": sign_at,
                "random_seconds": random_seconds,
            }
        )
        if config.requires_ai:
            print_to_user(OPENAI_USE_PROMPT)
        return config

    @classmethod
    def _validate_sign_at(cls, sign_at_str: str) -> Optional[str]:
        sign_at_str = sign_at_str.replace("：", ":").strip()

        try:
            sign_at = dt_time.fromisoformat(sign_at_str)
            crontab_expr = cls._time_to_crontab(sign_at)
        except ValueError:
            try:
                croniter(sign_at_str)
                crontab_expr = sign_at_str
            except CroniterBadCronError:
                return None
        return crontab_expr

    @staticmethod
    def _time_to_crontab(sign_at: time) -> str:
        return f"{sign_at.minute} {sign_at.hour} * * *"

    def load_sign_record(self):
        sign_record = {}
        if not self.sign_record_file.is_file():
            with open(self.sign_record_file, "w", encoding="utf-8") as fp:
                json.dump(sign_record, fp)
        else:
            with open(self.sign_record_file, "r", encoding="utf-8") as fp:
                sign_record = json.load(fp)
        return sign_record

    async def sign_a_chat(
        self,
        chat: SignChatV3,
    ):
        self.log(
            f"开始预热会话: chat_id={chat.chat_id}",
            stage="preheat",
            event="preheat_start",
            meta={"chat_id": chat.chat_id, "chat_name": getattr(chat, "name", "")},
        )
        try:
            # 预热会话，确保 peer/access_hash 可用
            await self.app.get_chat(chat.chat_id)
            self.log(
                f"预热会话成功: chat_id={chat.chat_id}",
                stage="preheat",
                event="preheat_primary_success",
                meta={"chat_id": chat.chat_id},
            )
        except Exception as e:
            # 兼容历史配置：部分会话可能保存了缺失负号的 chat_id
            try:
                from pyrogram.errors import ChannelInvalid, PeerIdInvalid
                is_peer_invalid = isinstance(e, (PeerIdInvalid, ChannelInvalid))
            except Exception:
                is_peer_invalid = any(x in str(e) for x in ("PEER_ID_INVALID", "CHANNEL_INVALID"))

            if is_peer_invalid and isinstance(chat.chat_id, int):
                last_error = e
                # First attempt: If it's a positive ID, try get_users (which may still fail if it's completely unknown)
                if chat.chat_id > 0:
                    try:
                        await self.app.get_users(chat.chat_id)
                        self.log(
                            f"预热会话使用 get_users 成功: {chat.chat_id}",
                            level="WARNING",
                            stage="preheat",
                            event="preheat_by_user_id_success",
                            meta={"chat_id": chat.chat_id},
                        )
                        last_error = None
                    except Exception as e2:
                        last_error = e2

                # Second attempt: Try fetching by cached username BEFORE blind negative guessing
                cached = self._find_cached_chat(chat.chat_id, chat.name)
                if cached:
                    username = cached.get("username")
                    cached_id = cached.get("id")
                    if username:
                        try:
                            resolved = await self.app.get_chat(username)
                            self.log(
                                f"预热会话使用缓存用户名成功: {chat.chat_id} -> @{username}",
                                level="WARNING",
                                stage="preheat",
                                event="preheat_by_username_success",
                                meta={"chat_id": chat.chat_id, "username": username},
                            )
                            chat.chat_id = resolved.id
                            last_error = None
                        except Exception as e2:
                            last_error = e2
                    if last_error is not None and cached_id and cached_id != chat.chat_id:
                        try:
                            await self.app.get_chat(cached_id)
                            self.log(
                                f"预热会话使用缓存 chat_id 成功: {chat.chat_id} -> {cached_id}",
                                level="WARNING",
                                stage="preheat",
                                event="preheat_by_cached_id_success",
                                meta={"chat_id": chat.chat_id, "cached_id": cached_id},
                            )
                            chat.chat_id = cached_id
                            last_error = None
                        except Exception as e2:
                            last_error = e2

                # Third attempt: Try guessing negative variants only if previous recovery did not succeed
                if last_error is not None:
                    candidates = []
                    if chat.chat_id > 0:
                        candidates.append(-chat.chat_id)
                        candidates.append(int(f"-100{chat.chat_id}"))
                    elif chat.chat_id < 0:
                        if not str(chat.chat_id).startswith("-100"):
                            candidates.append(int(f"-100{abs(chat.chat_id)}"))

                    for candidate in candidates:
                        if candidate == chat.chat_id:
                            continue
                        try:
                            await self.app.get_chat(candidate)
                            self.log(
                                f"预热会话使用回退 chat_id 成功: {chat.chat_id} -> {candidate}",
                                level="WARNING",
                                stage="preheat",
                                event="preheat_by_fallback_id_success",
                                meta={"chat_id": chat.chat_id, "candidate": candidate},
                            )
                            chat.chat_id = candidate
                            last_error = None
                            break
                        except Exception as e2:
                            last_error = e2
                            continue

                if last_error is not None:
                    self.log(
                        f"预热会话失败: chat_id={chat.chat_id}, error={type(last_error).__name__}: {last_error}",
                        level="ERROR",
                        stage="preheat",
                        event="preheat_failed",
                        meta={"chat_id": chat.chat_id, "error_type": type(last_error).__name__},
                    )
                    raise RuntimeError(
                        f"Failed to preheat chat_id {chat.chat_id}: {last_error}"
                    ) from last_error
            else:
                self.log(
                    f"预热会话失败: chat_id={chat.chat_id}, error={type(e).__name__}: {e}",
                    level="ERROR",
                    stage="preheat",
                    event="preheat_failed",
                    meta={"chat_id": chat.chat_id, "error_type": type(e).__name__},
                )
                raise RuntimeError(
                    f"Failed to preheat chat_id {chat.chat_id}: {e}"
                ) from e
        self.context.last_callback_texts.pop(chat.chat_id, None)
        self.log(
            f"开始执行 chat: {chat.chat_id}",
            stage="action",
            event="chat_execution_started",
            meta={"chat_id": chat.chat_id, "chat_name": getattr(chat, "name", "")},
        )
        for index, action in enumerate(chat.actions, start=1):
            self.log(
                f"等待处理动作 #{index}: {action}",
                stage="action",
                event="action_started",
                meta={"chat_id": chat.chat_id, "action_index": index, "action": str(action)},
            )
            await self.wait_for(chat, action)
            self.log(
                f"处理完成 #{index}: {action}",
                stage="action",
                event="action_completed",
                meta={"chat_id": chat.chat_id, "action_index": index, "action": str(action)},
            )
            self.context.waiting_message = None
            await asyncio.sleep(chat.action_interval)

    async def run(
        self, num_of_dialogs=20, only_once: bool = False, force_rerun: bool = False
    ):
        if self.app.in_memory or self.app.session_string:
            return await self.in_memory_run(
                num_of_dialogs, only_once=only_once, force_rerun=force_rerun
            )
        return await self.normal_run(
            num_of_dialogs, only_once=only_once, force_rerun=force_rerun
        )

    async def in_memory_run(
        self, num_of_dialogs=20, only_once: bool = False, force_rerun: bool = False
    ):
        async with self.app:
            await self.normal_run(
                num_of_dialogs, only_once=only_once, force_rerun=force_rerun
            )

    async def normal_run(
        self, num_of_dialogs=20, only_once: bool = False, force_rerun: bool = False
    ):
        if self.user is None:
            await self.login(num_of_dialogs, print_chat=True)

        config = self.load_config(self.cfg_cls)
        if config.requires_ai:
            self.ensure_ai_cfg()

        sign_record = self.load_sign_record()
        chat_ids = [c.chat_id for c in config.chats]
        need_update_handlers = bool(getattr(config, "requires_updates", True))
        message_handler_ref = None
        edited_handler_ref = None

        async def sign_once():
            success_count = 0
            total_chats = len(config.chats)
            for index, chat in enumerate(config.chats):
                self.context.sign_chats[chat.chat_id].append(chat)
                try:
                    await self.sign_a_chat(chat)
                    success_count += 1
                except (errors.RPCError, BusinessRetryableError) as _e:
                    self.log(f"签到失败: {_e} \nchat: \n{chat}")
                    logger.warning(_e, exc_info=True)
                    continue

                self.context.chat_messages[chat.chat_id].clear()
                if index < total_chats - 1 and config.sign_interval > 0:
                    await asyncio.sleep(config.sign_interval)

            if success_count == 0 and len(config.chats) > 0:
                raise BusinessRetryableError("所有会话均执行失败（详细请看运行日志）")

            sign_record[str(now.date())] = now.isoformat()
            with open(self.sign_record_file, "w", encoding="utf-8") as fp:
                json.dump(sign_record, fp)

        def need_sign(last_date_str):
            if force_rerun:
                return True
            if last_date_str not in sign_record:
                return True
            _last_sign_at = datetime.fromisoformat(sign_record[last_date_str])
            self.log(f"上次执行时间: {_last_sign_at}")
            _cron_it = croniter(self._validate_sign_at(config.sign_at), _last_sign_at)
            _next_run: datetime = _cron_it.next(datetime)
            if _next_run > now:
                self.log("当前未到下次执行时间，无需执行")
                return False
            return True

        while True:
            if need_update_handlers and message_handler_ref is None:
                self.log(f"adding message handlers for chats: {chat_ids}")
                message_handler_ref = self.app.add_handler(
                    MessageHandler(self.on_message, filters.chat(chat_ids))
                )
                edited_handler_ref = self.app.add_handler(
                    EditedMessageHandler(self.on_edited_message, filters.chat(chat_ids))
                )
            try:
                async with self.app:
                    now = get_now()
                    self.log(f"当前时间: {now}")
                    now_date_str = str(now.date())
                    self.context = self.ensure_ctx()
                    if need_sign(now_date_str):
                        if only_once and config.random_seconds > 0:
                            delay = random.randint(0, int(config.random_seconds))
                            if delay > 0:
                                self.log(f"单次执行随机延迟: {delay} 秒")
                                await asyncio.sleep(delay)
                        await sign_once()

            except (OSError, errors.Unauthorized) as e:
                logger.exception(e)
                await asyncio.sleep(30)
                continue

            if only_once:
                break
            cron_it = croniter(self._validate_sign_at(config.sign_at), now)
            next_run: datetime = cron_it.next(datetime) + timedelta(
                seconds=random.randint(0, int(config.random_seconds))
            )
            self.log(f"下次运行时间: {next_run}")
            await asyncio.sleep((next_run - now).total_seconds())


        if message_handler_ref:
            try:
                self.app.remove_handler(*message_handler_ref)
            except Exception:
                pass
        if edited_handler_ref:
            try:
                self.app.remove_handler(*edited_handler_ref)
            except Exception:
                pass

    async def run_once(self, num_of_dialogs):
        return await self.run(num_of_dialogs, only_once=True, force_rerun=True)

    async def send_text(
        self, chat_id: int, text: str, delete_after: int = None, **kwargs
    ):
        if self.user is None:
            await self.login(print_chat=False)
        async with self.app:
            await self.send_message(chat_id, text, delete_after, **kwargs)

    async def send_dice_cli(
        self,
        chat_id: Union[str, int],
        emoji: str = "🎲",
        delete_after: int = None,
        **kwargs,
    ):
        if self.user is None:
            await self.login(print_chat=False)
        async with self.app:
            await self.send_dice(chat_id, emoji, delete_after, **kwargs)

    async def _on_message(self, client: Client, message: Message):
        await store_incoming_message(
            message=message,
            context=self.context,
            log=self.log,
        )

    async def on_message(self, client: Client, message: Message):
        await handle_incoming_message(
            client=client,
            message=message,
            context=self.context,
            log=self.log,
        )

    async def on_edited_message(self, client, message: Message):
        await handle_edited_message(
            client=client,
            message=message,
            context=self.context,
            log=self.log,
        )

    def _clean_text_for_match(self, text: str) -> str:
        return clean_text_for_match(text)

    def _clean_text_for_send(self, text: str) -> str:
        return clean_text_for_send(text)

    async def _click_keyboard_by_text(
        self, action: ClickKeyboardByTextAction, message: Message
    ):
        return await click_keyboard_by_text(
            action=action,
            message=message,
            app=self.app,
            log=self.log,
            send_message=self.send_message,
            request_callback_answer=self.request_callback_answer,
            clean_text_for_match=self._clean_text_for_match,
        )

    async def _reply_by_calculation_problem(
        self, action: ReplyByCalculationProblemAction, message
    ):
        return await reply_by_calculation_problem(
            message=message,
            log=self.log,
            send_message=self.send_message,
            get_ai_tools=self.get_ai_tools,
        )

    async def _reply_by_image_recognition(
        self, action: ReplyByImageRecognitionAction, message
    ):
        return await reply_by_image_recognition(
            message=message,
            app=self.app,
            log=self.log,
            send_message=self.send_message,
            clean_text_for_send=self._clean_text_for_send,
            get_ai_tools=self.get_ai_tools,
        )

    async def _click_button_by_calculation_problem(
        self, action: ClickButtonByCalculationProblemAction, message
    ):
        return await click_button_by_calculation_problem(
            message=message,
            log=self.log,
            click_keyboard_by_text=self._click_keyboard_by_text,
            get_ai_tools=self.get_ai_tools,
        )

    async def _click_button_by_poetry_fill(
        self, action: ClickButtonByPoetryFillAction, message
    ):
        return await click_button_by_poetry_fill(
            message=message,
            app=self.app,
            chat_messages=self.context.chat_messages,
            log=self.log,
            clean_text_for_send=self._clean_text_for_send,
            click_keyboard_by_text=self._click_keyboard_by_text,
            get_ai_tools=self.get_ai_tools,
        )

    async def _choose_option_by_image(self, action: ChooseOptionByImageAction, message):
        return await choose_option_by_image(
            message=message,
            app=self.app,
            log=self.log,
            request_callback_answer=self.request_callback_answer,
            get_ai_tools=self.get_ai_tools,
        )

    async def _dispatch_action_on_message(self, action: ActionT, message: Message) -> bool:
        return await dispatch_action_on_message(
            action=action,
            message=message,
            click_keyboard_by_text=self._click_keyboard_by_text,
            reply_by_calculation_problem=self._reply_by_calculation_problem,
            choose_option_by_image=self._choose_option_by_image,
            reply_by_image_recognition=self._reply_by_image_recognition,
            click_button_by_calculation_problem=self._click_button_by_calculation_problem,
            click_button_by_poetry_fill=self._click_button_by_poetry_fill,
        )

    async def wait_for(self, chat: SignChatV3, action: ActionT, timeout=15):
        return await wait_for_action(
            chat=chat,
            action=action,
            timeout=timeout,
            app=self.app,
            context=self.context,
            log=self.log,
            send_message=self.send_message,
            send_dice=self.send_dice,
            dispatch_action=self._dispatch_action_on_message,
            clean_text_for_match=self._clean_text_for_match,
        )

    async def request_callback_answer(
        self,
        client: Client,
        chat_id: Union[int, str],
        message_id: int,
        callback_data: Union[str, bytes],
        **kwargs,
    ) -> bool:
        return await request_callback_answer(
            client=client,
            chat_id=chat_id,
            message_id=message_id,
            callback_data=callback_data,
            log=self.log,
            callback_text_store=self.context.last_callback_texts,
            **kwargs,
        )

    async def schedule_messages(
        self,
        chat_id: Union[int, str],
        text: str,
        crontab: str = None,
        next_times: int = 1,
        random_seconds: int = 0,
    ):
        return await schedule_messages(
            app=self.app,
            user=self.user,
            login=self.login,
            log=self.log,
            print_to_user=print_to_user,
            get_now=get_now,
            chat_id=chat_id,
            text=text,
            crontab=crontab,
            next_times=next_times,
            random_seconds=random_seconds,
        )

    async def get_schedule_messages(self, chat_id):
        return await get_scheduled_messages(
            app=self.app,
            user=self.user,
            login=self.login,
            print_to_user=print_to_user,
            chat_id=chat_id,
        )


class UserMonitor(BaseUserWorker[MonitorConfig]):
    _workdir = ".monitor"
    _tasks_dir = "monitors"
    cfg_cls = MonitorConfig
    config: MonitorConfig

    def ask_one(self):
        input_ = UserInput()
        chat_id = (input_("Chat ID（登录时最近对话输出中的ID）: ")).strip()
        if not chat_id.startswith("@"):
            chat_id = int(chat_id)
        rules = ["exact", "contains", "regex", "all"]
        while rule := (input_(f"匹配规则({', '.join(rules)}): ") or "exact"):
            if rule in rules:
                break
            print_to_user("不存在的规则, 请重新输入!")
        rule_value = None
        if rule != "all":
            while not (rule_value := input_("规则值（不可为空）: ")):
                print_to_user("不可为空！")
                continue
        from_user_ids = (
            input_(
                "只匹配来自特定用户ID的消息（多个用逗号隔开, 匹配所有用户直接回车）: "
            )
            or None
        )
        always_ignore_me = input_("总是忽略自己发送的消息（y/N）: ").lower() == "y"
        if from_user_ids:
            from_user_ids = [
                i if i.startswith("@") else int(i) for i in from_user_ids.split(",")
            ]
        default_send_text = input_("默认发送文本（不需要则回车）: ") or None
        ai_reply = False
        ai_prompt = None
        use_ai_reply = input_("是否使用AI进行回复(y/N): ") or "n"
        if use_ai_reply.lower() == "y":
            ai_reply = True
            while not (ai_prompt := input_("输入你的提示词（作为`system prompt`）: ")):
                print_to_user("不可为空！")
                continue
            print_to_user(OPENAI_USE_PROMPT)

        send_text_search_regex = None
        if not ai_reply:
            send_text_search_regex = (
                input_("从消息中提取发送文本的正则表达式（不需要则直接回车）: ") or None
            )

        if default_send_text or ai_reply or send_text_search_regex:
            delete_after = (
                input_(
                    "发送消息后等待N秒进行删除（'0'表示立即删除, 不需要删除直接回车）， N: "
                )
                or None
            )
            if delete_after:
                delete_after = int(delete_after)
            forward_to_chat_id = (
                input_("转发消息到该聊天ID，默认为消息来源：")
            ).strip()
            if forward_to_chat_id and not forward_to_chat_id.startswith("@"):
                forward_to_chat_id = int(forward_to_chat_id)
        else:
            delete_after = None
            forward_to_chat_id = None

        push_via_server_chan = (
            input_("是否通过Server酱推送消息(y/N): ") or "n"
        ).lower() == "y"
        server_chan_send_key = None
        if push_via_server_chan:
            server_chan_send_key = (
                input_(
                    "Server酱的SendKey（不填将从环境变量`SERVER_CHAN_SEND_KEY`读取）: "
                )
                or None
            )

        forward_to_external = (
            input_("是否需要转发到外部（UDP, Http）(y/N): ").lower() == "y"
        )
        external_forwards = None
        if forward_to_external:
            external_forwards = []
            if input_("是否需要转发到UDP(y/N): ").lower() == "y":
                addr = input_("请输入UDP服务器地址和端口（形如`127.0.0.1:1234`）: ")
                host, port = addr.split(":")
                external_forwards.append(
                    {
                        "host": host,
                        "port": int(port),
                    }
                )

            if input_("是否需要转发到Http(y/N): ").lower() == "y":
                url = input_("请输入Http地址（形如`http://127.0.0.1:1234`）: ")
                external_forwards.append(
                    {
                        "url": url,
                    }
                )

        return MatchConfig.parse_obj(
            {
                "chat_id": chat_id,
                "rule": rule,
                "rule_value": rule_value,
                "from_user_ids": from_user_ids,
                "always_ignore_me": always_ignore_me,
                "default_send_text": default_send_text,
                "ai_reply": ai_reply,
                "ai_prompt": ai_prompt,
                "send_text_search_regex": send_text_search_regex,
                "delete_after": delete_after,
                "forward_to_chat_id": forward_to_chat_id,
                "push_via_server_chan": push_via_server_chan,
                "server_chan_send_key": server_chan_send_key,
                "external_forwards": external_forwards,
            }
        )

    def ask_for_config(self) -> "MonitorConfig":
        i = 1
        print_to_user(f"开始配置任务<{self.task_name}>")
        print_to_user(
            "聊天chat id和用户user id均同时支持整数id和字符串username, username必须以@开头，如@neo"
        )
        match_cfgs = []
        while True:
            print_to_user(f"\n配置第{i}个监控项")
            try:
                match_cfgs.append(self.ask_one())
            except Exception as e:
                print_to_user(e)
                print_to_user("配置失败")
                i -= 1
            continue_ = input("继续配置？(y/N)：")
            if continue_.strip().lower() != "y":
                break
            i += 1
        config = MonitorConfig(match_cfgs=match_cfgs)
        if config.requires_ai:
            print_to_user(OPENAI_USE_PROMPT)
        return config

    @classmethod
    async def udp_forward(cls, f: UDPForward, message: Message):
        data = str(message).encode("utf-8")
        loop = asyncio.get_running_loop()
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: _UDPProtocol(), remote_addr=(f.host, f.port)
        )
        try:
            transport.sendto(data)
        finally:
            transport.close()

    @classmethod
    async def http_api_callback(cls, f: HttpCallback, message: Message):
        headers = f.headers or {}
        headers.update({"Content-Type": "application/json"})
        content = str(message).encode("utf-8")
        async with httpx.AsyncClient() as client:
            await client.post(
                str(f.url),
                content=content,
                headers=headers,
                timeout=10,
            )

    async def forward_to_external(self, match_cfg: MatchConfig, message: Message):
        if not match_cfg.external_forwards:
            return
        for forward in match_cfg.external_forwards:
            self.log(f"转发消息至{forward}")
            if isinstance(forward, UDPForward):
                asyncio.create_task(
                    self.udp_forward(
                        forward,
                        message,
                    )
                )
            elif isinstance(forward, HttpCallback):
                asyncio.create_task(
                    self.http_api_callback(
                        forward,
                        message,
                    )
                )

    async def on_message(self, client, message: Message):
        for match_cfg in self.config.match_cfgs:
            if not match_cfg.match(message):
                continue
            self.log(f"匹配到监控项：{match_cfg}")
            await self.forward_to_external(match_cfg, message)
            try:
                send_text = await self.get_send_text(match_cfg, message)
                if not send_text:
                    self.log("发送内容为空", level="WARNING")
                else:
                    forward_to_chat_id = match_cfg.forward_to_chat_id or message.chat.id
                    self.log(f"发送文本：{send_text}至{forward_to_chat_id}")
                    await self.send_message(
                        forward_to_chat_id,
                        send_text,
                        delete_after=match_cfg.delete_after,
                    )

                if match_cfg.push_via_server_chan:
                    server_chan_send_key = (
                        match_cfg.server_chan_send_key
                        or os.environ.get("SERVER_CHAN_SEND_KEY")
                    )
                    if not server_chan_send_key:
                        self.log("未配置Server酱的SendKey", level="WARNING")
                    else:
                        await sc_send(
                            server_chan_send_key,
                            f"匹配到监控项：{match_cfg.chat_id}",
                            f"消息内容为:\n\n{message.text}",
                        )
            except IndexError as e:
                logger.exception(e)

    async def get_send_text(self, match_cfg: MatchConfig, message: Message) -> str:
        send_text = match_cfg.get_send_text(message.text)
        if match_cfg.ai_reply and match_cfg.ai_prompt:
            send_text = await self.get_ai_tools().get_reply(
                match_cfg.ai_prompt,
                message.text,
            )
        return send_text

    async def run(self, num_of_dialogs=20):
        if self.user is None:
            await self.login(num_of_dialogs, print_chat=True)

        cfg = self.load_config(self.cfg_cls)
        if cfg.requires_ai:
            self.ensure_ai_cfg()

        self.app.add_handler(
            MessageHandler(self.on_message, filters.text & filters.chat(cfg.chat_ids)),
        )
        async with self.app:
            self.log("开始监控...")
            await idle()


class _UDPProtocol(asyncio.DatagramProtocol):
    """内部使用的UDP协议处理类"""

    def __init__(self):
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        pass  # 不需要处理接收的数据

    def error_received(self, exc):
        print(f"UDP error received: {exc}")
