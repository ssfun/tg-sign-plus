from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

from tg_signer.config import (
    ActionT,
    AssertSuccessByTextAction,
    ChooseOptionByImageAction,
    ClickButtonByCalculationProblemAction,
    ClickButtonByPoetryFillAction,
    ClickKeyboardByTextAction,
    ReplyByCalculationProblemAction,
    ReplyByImageRecognitionAction,
    SendDiceAction,
    SendTextAction,
    SignChatV3,
)

from .assert_actions import assert_success_by_text
from .message_helpers import message_version, readable_message


class BusinessRetryableError(RuntimeError):
    """仅用于业务失败重试。"""


ACTION_TYPES_WITH_HISTORY_FALLBACK = (
    ClickKeyboardByTextAction,
    ReplyByCalculationProblemAction,
    ChooseOptionByImageAction,
    ReplyByImageRecognitionAction,
    ClickButtonByCalculationProblemAction,
    ClickButtonByPoetryFillAction,
)

BUTTON_ACTION_TYPES = (
    ClickKeyboardByTextAction,
    ClickButtonByCalculationProblemAction,
    ClickButtonByPoetryFillAction,
)


async def dispatch_action_on_message(
    *,
    action: ActionT,
    message,
    click_keyboard_by_text: Callable[..., Awaitable[bool]],
    reply_by_calculation_problem: Callable[..., Awaitable[bool]],
    choose_option_by_image: Callable[..., Awaitable[bool]],
    reply_by_image_recognition: Callable[..., Awaitable[bool]],
    click_button_by_calculation_problem: Callable[..., Awaitable[bool]],
    click_button_by_poetry_fill: Callable[..., Awaitable[bool]],
) -> bool:
    if isinstance(action, ClickKeyboardByTextAction):
        return await click_keyboard_by_text(action, message)
    if isinstance(action, ReplyByCalculationProblemAction):
        return await reply_by_calculation_problem(action, message)
    if isinstance(action, ChooseOptionByImageAction):
        return await choose_option_by_image(action, message)
    if isinstance(action, ReplyByImageRecognitionAction):
        return await reply_by_image_recognition(action, message)
    if isinstance(action, ClickButtonByCalculationProblemAction):
        return await click_button_by_calculation_problem(action, message)
    if isinstance(action, ClickButtonByPoetryFillAction):
        return await click_button_by_poetry_fill(action, message)
    return False


async def wait_for_action(
    *,
    chat: SignChatV3,
    action: ActionT,
    timeout: int | float,
    app,
    context,
    log: Callable[..., None],
    send_message: Callable[..., Awaitable],
    send_dice: Callable[..., Awaitable],
    dispatch_action: Callable[..., Awaitable[bool]],
    clean_text_for_match: Callable[[str], str],
) -> None:
    if isinstance(action, SendTextAction):
        log(
            f"发送文本动作: {action.text}",
            stage="action",
            event="send_text_started",
            meta={"chat_id": chat.chat_id, "text": action.text, "delete_after": chat.delete_after},
        )
        await send_message(chat.chat_id, action.text, chat.delete_after)
        log(
            f"发送文本完成: {action.text}",
            stage="action",
            event="send_text_completed",
            meta={"chat_id": chat.chat_id, "text": action.text},
        )
        return None
    if isinstance(action, SendDiceAction):
        log(
            f"发送骰子动作: {action.dice}",
            stage="action",
            event="send_dice_started",
            meta={"chat_id": chat.chat_id, "emoji": action.dice, "delete_after": chat.delete_after},
        )
        await send_dice(chat.chat_id, action.dice, chat.delete_after)
        log(
            f"发送骰子完成: {action.dice}",
            stage="action",
            event="send_dice_completed",
            meta={"chat_id": chat.chat_id, "emoji": action.dice},
        )
        return None
    if isinstance(action, AssertSuccessByTextAction):
        ok = await assert_success_by_text(
            action=action,
            chat=chat,
            app=app,
            context=context,
            log=log,
            clean_text_for_match=clean_text_for_match,
        )
        if not ok:
            raise BusinessRetryableError(
                f"Success assertion failed. chat_id={chat.chat_id}, keywords={action.keywords}"
            )
        return None

    log(
        f"开始等待动作命中: {action}",
        stage="action",
        event="wait_started",
        meta={"chat_id": chat.chat_id, "action": str(action), "timeout": timeout},
    )
    context.waiter.add(chat.chat_id)
    start = time.perf_counter()
    processed_versions = set()
    try:
        while time.perf_counter() - start < timeout:
            await asyncio.sleep(0.3)
            messages_dict = context.chat_messages.get(chat.chat_id)
            if not messages_dict:
                continue
            messages = [message for message in messages_dict.values() if message is not None]
            if not messages:
                continue
            for message in messages:
                version = message_version(message)
                if version in processed_versions:
                    continue
                processed_versions.add(version)
                context.waiting_message = message
                ok = await dispatch_action(action, message)
                if ok:
                    log(
                        f"动作命中实时消息: {readable_message(message)}",
                        stage="action",
                        event="wait_matched_live_message",
                        meta={"chat_id": chat.chat_id, "action": str(action), "message_id": message.id},
                    )
                    context.chat_messages[chat.chat_id][message.id] = None
                    return None
                log(
                    f"忽略消息: {readable_message(message)}",
                    stage="message",
                    event="wait_ignored_message",
                    meta={"chat_id": chat.chat_id, "action": str(action), "message_id": message.id},
                )

        if isinstance(action, ACTION_TYPES_WITH_HISTORY_FALLBACK):
            history_messages = None
            try:
                history_messages = []
                async for message in app.get_chat_history(chat.chat_id, limit=5):
                    history_messages.append(message)
            except Exception as e:
                log(
                    f"历史消息查询失败: {e}",
                    level="WARNING",
                    stage="message",
                    event="history_fetch_failed",
                    meta={"chat_id": chat.chat_id, "action": str(action), "error_type": type(e).__name__},
                )

            if history_messages:
                for message in history_messages:
                    try:
                        ok = await dispatch_action(action, message)
                    except Exception as e:
                        log(
                            f"历史消息回退执行失败: {e}",
                            level="ERROR",
                            stage="action",
                            event="history_dispatch_failed",
                            meta={"chat_id": chat.chat_id, "action": str(action), "message_id": getattr(message, 'id', None), "error_type": type(e).__name__},
                        )
                        raise
                    if ok:
                        log(
                            "实时更新未命中，已通过最近历史消息继续执行",
                            stage="message",
                            event="history_dispatch_succeeded",
                            meta={"chat_id": chat.chat_id, "action": str(action), "message_id": getattr(message, 'id', None)},
                        )
                        return None

        log(
            f"等待超时: \nchat: \n{chat} \naction: {action}",
            level="WARNING",
            stage="action",
            event="wait_timeout",
            meta={"chat_id": chat.chat_id, "action": str(action), "timeout": timeout},
        )
        if isinstance(action, BUTTON_ACTION_TYPES):
            raise BusinessRetryableError(
                f"Target button not found within {timeout}s. chat_id={chat.chat_id}, action={action}"
            )
        return None
    finally:
        context.waiter.discard(chat.chat_id)
        context.waiting_message = None
