from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from pyrogram.types import Message

from tg_signer.config import AssertSuccessByTextAction
from tg_signer.message_helpers import get_message_text_content, message_version, readable_message


def _read_float_env(name: str, default: float, minimum: float = 1.0) -> float:
    try:
        return max(float(os.environ.get(name, default)), minimum)
    except (TypeError, ValueError):
        return default


def _message_time(message: Message) -> datetime | None:
    message_time = getattr(message, "edit_date", None) or getattr(message, "date", None)
    if message_time and message_time.tzinfo is None:
        return message_time.replace(tzinfo=timezone.utc)
    return message_time


def _message_sort_key(message: Message) -> tuple:
    return (_message_time(message) or datetime.min.replace(tzinfo=timezone.utc), message.id)


def _message_is_after_action(message: Message, action_started_at: datetime) -> bool:
    message_time = _message_time(message)
    if message_time is None:
        return True
    return message_time >= action_started_at - timedelta(seconds=1)


async def assert_success_by_text(
    *,
    action: AssertSuccessByTextAction,
    chat,
    app,
    context,
    log: Callable[..., None],
    clean_text_for_match: Callable[[str], str],
    timeout: float = 15.0,
) -> bool:
    timeout = max(timeout, _read_float_env("TG_SUCCESS_ASSERT_TIMEOUT", 30.0))
    keywords = [item.strip() for item in action.keywords if item and item.strip()]
    if not keywords:
        log(
            "成功判定失败：未配置有效关键字",
            level="WARNING",
            stage="action",
            event="success_assert_empty_keywords",
            meta={"chat_id": chat.chat_id},
        )
        return False

    keyword_pairs = [
        (keyword, normalized_keyword)
        for keyword in keywords
        if (normalized_keyword := clean_text_for_match(keyword))
    ]

    log(
        f"开始等待签到结果（超时 {timeout}s）",
        stage="action",
        event="success_assert_wait_started",
        meta={"chat_id": chat.chat_id, "keywords": ", ".join(keywords), "timeout": timeout},
    )

    start = time.perf_counter()
    action_started_at = datetime.now(timezone.utc)
    checked_message_versions = set()
    last_checked_callback_text = None

    while True:
        last_callback_text = str((context.last_callback_texts or {}).get(chat.chat_id, "") or "")
        if last_callback_text and last_callback_text != last_checked_callback_text:
            last_checked_callback_text = last_callback_text
            normalized_callback_text = clean_text_for_match(last_callback_text)
            log(
                f"开始根据最近一次弹窗判断签到结果: {last_callback_text}",
                stage="action",
                event="success_assert_started",
                meta={"chat_id": chat.chat_id, "source": "callback", "keywords": ", ".join(keywords)},
            )
            for keyword, normalized_keyword in keyword_pairs:
                if normalized_keyword in normalized_callback_text:
                    log(
                        f"成功命中关键字: {keyword}",
                        level="success",
                        stage="result",
                        event="success_assert_matched",
                        meta={"chat_id": chat.chat_id, "source": "callback", "keyword": keyword},
                    )
                    return True

        messages_dict = context.chat_messages.get(chat.chat_id) or {}
        messages = [
            message
            for message in messages_dict.values()
            if isinstance(message, Message) and _message_is_after_action(message, action_started_at)
        ]

        for message in sorted(messages, key=_message_sort_key, reverse=True):
            current_id = message_version(message)
            if current_id in checked_message_versions:
                continue
            checked_message_versions.add(current_id)
            message_text = get_message_text_content(message)
            normalized_text = clean_text_for_match(message_text)
            log(
                f"开始根据消息判断签到结果: {readable_message(message)}",
                stage="action",
                event="success_assert_started",
                meta={"chat_id": chat.chat_id, "source": "message", "message_id": message.id, "keywords": ", ".join(keywords)},
            )
            for keyword, normalized_keyword in keyword_pairs:
                if normalized_keyword in normalized_text:
                    log(
                        f"成功命中关键字: {keyword}",
                        level="success",
                        stage="result",
                        event="success_assert_matched",
                        meta={"chat_id": chat.chat_id, "source": "message", "message_id": message.id, "keyword": keyword},
                    )
                    return True

        if time.perf_counter() - start >= timeout:
            break

        await asyncio.sleep(0.5)

    history_messages = []
    try:
        async for message in app.get_chat_history(chat.chat_id, limit=5):
            if _message_is_after_action(message, action_started_at):
                history_messages.append(message)
    except Exception as e:
        log(
            f"查询最近消息失败: {e}",
            level="WARNING",
            stage="message",
            event="success_assert_history_fetch_failed",
            meta={"chat_id": chat.chat_id, "error_type": type(e).__name__},
        )

    latest_message = None
    for message in sorted(history_messages, key=_message_sort_key, reverse=True):
        latest_message = message
        message_text = get_message_text_content(message)
        normalized_text = clean_text_for_match(message_text)
        log(
            f"开始根据历史消息判断签到结果: {readable_message(message)}",
            stage="action",
            event="success_assert_started",
            meta={"chat_id": chat.chat_id, "source": "history", "message_id": message.id, "keywords": ", ".join(keywords)},
        )
        for keyword, normalized_keyword in keyword_pairs:
            if normalized_keyword in normalized_text:
                log(
                    f"成功命中关键字（历史消息兜底）: {keyword}",
                    level="success",
                    stage="result",
                    event="success_assert_matched",
                    meta={"chat_id": chat.chat_id, "source": "history", "message_id": message.id, "keyword": keyword},
                )
                return True

    last_callback_text = str((context.last_callback_texts or {}).get(chat.chat_id, "") or "")
    log(
        f"等待 {timeout}s 后仍未命中任何成功关键字",
        level="WARNING",
        stage="result",
        event="success_assert_failed",
        meta={
            "chat_id": chat.chat_id,
            "keywords": ", ".join(keywords),
            "callback_text": last_callback_text,
            "message_id": latest_message.id if latest_message else None,
            "message_text": get_message_text_content(latest_message) if latest_message else None,
        },
    )
    return False
