from __future__ import annotations

import asyncio
import hashlib
import os
import random
import re
import string
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Awaitable, Callable, Iterable

from pyrogram import errors
from pyrogram.types import InlineKeyboardMarkup, Message, ReplyKeyboardMarkup

from tg_signer.event_contract import (
    EVENT_ENGINE_BUTTON_CALLBACK_RELEASED_FOR_RETRY,
    EVENT_ENGINE_CAPTCHA_RESULT_TEXT_PREEMPTED,
    EVENT_ENGINE_HARD_TIMEOUT_LATE_CANCELLED,
    EVENT_ENGINE_HARD_TIMEOUT_LATE_COMPLETED,
    EVENT_ENGINE_HARD_TIMEOUT_LATE_EXCEPTION,
    EVENT_ENGINE_MESSAGE_PROCESSING_CANCELLED,
)
from tg_signer.config import (
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
    WaitAction,
)

from .callback_actions import CallbackAnswerResult
from .message_helpers import extract_keyboard_options, get_message_text_content, message_version, readable_message
from .text_cleaners import clean_text_for_match, clean_text_for_send
from tg_signer_contracts.errors import BusinessRetryableError
from tg_signer_contracts.wait_budget import action_wait_budget


class EventRunStatus(str, Enum):
    SUCCESS = "success"
    CHECKED = "checked"
    FAILED = "failed"


@dataclass
class EventRunResult:
    status: EventRunStatus
    message: str = ""


class EventHardTimeoutError(asyncio.TimeoutError):
    def __init__(self, operation: str, timeout: float):
        super().__init__(f"{operation} timed out after {timeout}s")
        self.operation = operation
        self.timeout = timeout


def _retryable_error_type(exc: BaseException) -> str:
    if isinstance(exc, EventHardTimeoutError):
        return "TimeoutError"
    return type(exc).__name__


@dataclass
class EventRunSpec:
    send_actions: list[SendTextAction | SendDiceAction | WaitAction] = field(default_factory=list)
    response_actions: list[
        SendTextAction
        | SendDiceAction
        | WaitAction
        | ClickKeyboardByTextAction
        | ChooseOptionByImageAction
        | ReplyByCalculationProblemAction
        | ReplyByImageRecognitionAction
        | ClickButtonByCalculationProblemAction
        | ClickButtonByPoetryFillAction
    ] = field(default_factory=list)
    click_texts: list[str] = field(default_factory=list)
    choose_option_by_image: bool = False
    reply_by_calculation: bool = False
    reply_by_image: bool = False
    image_caption_patterns: list[str] = field(default_factory=list)
    captcha_lengths: list[int] = field(default_factory=list)
    captcha_charsets: list[str] = field(default_factory=list)
    captcha_case: str = "preserve"
    reply_captcha_to_message: bool = False
    click_by_calculation: bool = False
    click_by_poetry: bool = False
    success_keywords: list[str] = field(default_factory=list)
    requires_result: bool = False


def _read_float_env(name: str, default: float, minimum: float = 1.0) -> float:
    try:
        return max(float(os.environ.get(name, default)), minimum)
    except (TypeError, ValueError):
        return default


def _optional_float(value, *, minimum: float = 0.0) -> float | None:
    try:
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        return max(float(value), minimum)
    except (TypeError, ValueError):
        return None


def _optional_int(value, *, minimum: int = 0) -> int | None:
    try:
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        return max(int(value), minimum)
    except (TypeError, ValueError):
        return None


def _optional_bool(value) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return None


def _dedupe(items: Iterable[str]) -> list[str]:
    seen = set()
    values = []
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


def _extract_button_texts(message: Message) -> list[str]:
    options = extract_keyboard_options(message)
    if options:
        return options
    reply_markup = getattr(message, "reply_markup", None)
    rows = getattr(reply_markup, "inline_keyboard", None) or getattr(reply_markup, "keyboard", None) or []
    texts = []
    for row in rows:
        for button in row:
            text = getattr(button, "text", "") or ""
            if text:
                texts.append(text)
    return texts


def _count_poetry_fill_blanks(text: str) -> int:
    return len(re.findall(r"[░□＿_]", text or ""))


def build_event_spec(chat: SignChatV3) -> EventRunSpec:
    spec = EventRunSpec()
    collecting_initial_sends = True
    for action in chat.actions:
        if isinstance(action, (SendTextAction, SendDiceAction, WaitAction)):
            if collecting_initial_sends:
                spec.send_actions.append(action)
            else:
                spec.response_actions.append(action)
            continue
        collecting_initial_sends = False
        if isinstance(action, ClickKeyboardByTextAction):
            spec.response_actions.append(action)
            spec.click_texts.append(action.text)
        elif isinstance(action, ChooseOptionByImageAction):
            spec.response_actions.append(action)
            spec.choose_option_by_image = True
        elif isinstance(action, ReplyByCalculationProblemAction):
            spec.response_actions.append(action)
            spec.reply_by_calculation = True
        elif isinstance(action, ReplyByImageRecognitionAction):
            spec.response_actions.append(action)
            spec.reply_by_image = True
            if action.caption_pattern:
                spec.image_caption_patterns.append(action.caption_pattern)
            spec.captcha_lengths.extend(action.captcha_lengths or [])
            if action.captcha_charset:
                spec.captcha_charsets.append(action.captcha_charset)
            if action.captcha_case != "preserve":
                spec.captcha_case = action.captcha_case
            if action.reply_to_message:
                spec.reply_captcha_to_message = True
        elif isinstance(action, ClickButtonByCalculationProblemAction):
            spec.response_actions.append(action)
            spec.click_by_calculation = True
        elif isinstance(action, ClickButtonByPoetryFillAction):
            spec.response_actions.append(action)
            spec.click_by_poetry = True
        elif isinstance(action, AssertSuccessByTextAction):
            spec.requires_result = True
            spec.success_keywords.extend(action.keywords)
    spec.click_texts = _dedupe(spec.click_texts)
    spec.success_keywords = _dedupe(spec.success_keywords)
    spec.image_caption_patterns = _dedupe(spec.image_caption_patterns)
    spec.captcha_lengths = sorted(set(spec.captcha_lengths))
    spec.captcha_charsets = _dedupe(spec.captcha_charsets)
    return spec


class SignEventRunner:
    def __init__(
        self,
        *,
        chat: SignChatV3,
        app,
        log: Callable[..., None],
        send_message: Callable[..., Awaitable],
        send_dice: Callable[..., Awaitable],
        request_callback_answer: Callable[..., Awaitable[bool]],
        get_ai_tools: Callable,
        timeout: float | None = None,
    ):
        self.chat = chat
        self.app = app
        self.log = log
        self.send_message = send_message
        self.send_dice = send_dice
        self.request_callback_answer = request_callback_answer
        self.get_ai_tools = get_ai_tools
        chat_timeout = _optional_float(getattr(chat, "event_timeout", None), minimum=1.0)
        self.timeout = timeout or chat_timeout or _read_float_env("TG_EVENT_ENGINE_TIMEOUT", 120.0)
        self.spec = build_event_spec(chat)
        self.finished = asyncio.Event()
        self.result: EventRunResult | None = None
        self.processed_versions = set()
        self.processing_versions = set()
        self.stale_attempt_versions = set()
        self.logged_skip_versions = set()
        self.unhandled_versions = set()
        self.message_skip_counts = {
            "finished": 0,
            "non_inbound": 0,
            "duplicate": 0,
            "concurrent_duplicate": 0,
            "unhandled": 0,
            "clicked_duplicate": 0,
            "cancelled": 0,
            "stale_attempt": 0,
        }
        self.sent_captcha_versions = set()
        self.captcha_result_text_preemptions = 0
        self.response_message_count = 0
        self.clicked_versions = set()
        self.history_duplicate_versions = set()
        self.history_filtered_versions = set()
        self.history_unhandled_versions = set()
        self.history_unhandled_duplicate_versions = set()
        self.callback_result_counts = {
            "confirmed": 0,
            "trusted_timeout": 0,
            "data_invalid_after_timeout": 0,
            "unconfirmed": 0,
        }
        self.message_lock = asyncio.Lock()
        self._completed_wait_seconds = 0
        self.current_response_index = 0
        self.retry_count = 0
        self.retry_suppressed_count = 0
        chat_retries = _optional_int(getattr(chat, "event_retries", None), minimum=0)
        chat_history_limit = _optional_int(getattr(chat, "event_history_limit", None), minimum=0)
        chat_history_failure_threshold = _optional_int(
            getattr(chat, "event_history_failure_threshold", None),
            minimum=0,
        )
        chat_history_rescue_interval = _optional_float(
            getattr(chat, "event_history_rescue_interval", None),
            minimum=0.0,
        )
        chat_history_rpc_timeout = _optional_float(
            getattr(chat, "event_history_rpc_timeout", None),
            minimum=1.0,
        )
        chat_history_result_max_age = _optional_float(
            getattr(chat, "event_history_result_max_age", None),
            minimum=0.0,
        )
        chat_retry_wait = _optional_float(getattr(chat, "event_retry_wait", None), minimum=0.0)
        chat_action_timeout = _optional_float(getattr(chat, "event_action_timeout", None), minimum=1.0)
        chat_send_timeout = _optional_float(getattr(chat, "event_send_timeout", None), minimum=1.0)
        chat_media_timeout = _optional_float(getattr(chat, "event_media_timeout", None), minimum=1.0)
        chat_ai_timeout = _optional_float(getattr(chat, "event_ai_timeout", None), minimum=1.0)
        chat_callback_timeout = _optional_float(getattr(chat, "event_callback_timeout", None), minimum=0.1)
        chat_callback_retries = _optional_int(getattr(chat, "event_callback_retries", None), minimum=1)
        self.max_inline_retries = (
            chat_retries
            if chat_retries is not None
            else int(_read_float_env("TG_EVENT_ENGINE_INLINE_RETRIES", 3, minimum=0))
        )
        self.history_limit = (
            chat_history_limit
            if chat_history_limit is not None
            else int(_read_float_env("TG_EVENT_ENGINE_HISTORY_LIMIT", 3, minimum=0))
        )
        self.retry_wait = (
            chat_retry_wait
            if chat_retry_wait is not None
            else _read_float_env("TG_EVENT_ENGINE_RETRY_WAIT", 2.0, minimum=0.0)
        )
        self.action_timeout = (
            chat_action_timeout
            if chat_action_timeout is not None
            else _read_float_env("TG_EVENT_ENGINE_ACTION_TIMEOUT", 45.0)
        )
        self.send_timeout = (
            chat_send_timeout
            if chat_send_timeout is not None
            else _read_float_env("TG_EVENT_ENGINE_SEND_TIMEOUT", self.action_timeout)
        )
        self.media_timeout = (
            chat_media_timeout
            if chat_media_timeout is not None
            else min(
                self.action_timeout,
                _read_float_env("TG_EVENT_ENGINE_MEDIA_TIMEOUT", 15.0, minimum=1.0),
            )
        )
        self.ai_timeout = (
            chat_ai_timeout
            if chat_ai_timeout is not None
            else min(
                self.action_timeout,
                _read_float_env("TG_EVENT_ENGINE_AI_TIMEOUT", 30.0, minimum=1.0),
            )
        )
        self.callback_timeout = (
            chat_callback_timeout
            if chat_callback_timeout is not None
            else _read_float_env("TG_CALLBACK_TIMEOUT", 10.0, minimum=0.1)
        )
        self.callback_timeout_configured = chat_callback_timeout is not None
        self.callback_retries = (
            chat_callback_retries
            if chat_callback_retries is not None
            else int(_read_float_env("TG_CALLBACK_RETRIES", 3, minimum=1))
        )
        self.callback_retries_configured = chat_callback_retries is not None
        self.history_rescue_interval = _read_float_env(
            "TG_EVENT_ENGINE_HISTORY_RESCUE_INTERVAL",
            5.0,
            minimum=1.0,
        ) if chat_history_rescue_interval is None else chat_history_rescue_interval
        self.history_rpc_timeout = _read_float_env(
            "TG_EVENT_ENGINE_HISTORY_RPC_TIMEOUT",
            8.0,
            minimum=1.0,
        ) if chat_history_rpc_timeout is None else chat_history_rpc_timeout
        self.history_failure_threshold = (
            chat_history_failure_threshold
            if chat_history_failure_threshold is not None
            else int(_read_float_env("TG_EVENT_ENGINE_HISTORY_FAILURE_THRESHOLD", 2, minimum=0))
        )
        self.history_result_max_age = _read_float_env(
            "TG_EVENT_ENGINE_HISTORY_RESULT_MAX_AGE",
            600.0,
            minimum=0.0,
        ) if chat_history_result_max_age is None else chat_history_result_max_age
        chat_ai_fallback = _optional_bool(getattr(chat, "event_ai_fallback", None))
        if chat_ai_fallback is None:
            self.ai_fallback_enabled = os.environ.get("TG_EVENT_ENGINE_AI_FALLBACK", "0").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        else:
            self.ai_fallback_enabled = chat_ai_fallback
        self._last_history_rescue_at = 0.0
        self.history_rescue_min_message_id: int | None = None
        self.history_rescue_tracked_message_ids: set[int] = set()
        self.history_scan_lock = asyncio.Lock()
        self.history_scan_counts = {
            "startup": 0,
            "rescue": 0,
            "failed": 0,
            "messages_seen": 0,
            "messages_allowed": 0,
            "messages_handled": 0,
            "duplicates": 0,
            "tracked_rechecks": 0,
            "expired": 0,
            "filtered_before_entry": 0,
            "filtered_expired": 0,
            "hard_failures_skipped": 0,
            "unhandled_duplicates": 0,
            "circuit_opened": 0,
            "concurrent_skipped": 0,
            "cancelled": 0,
        }
        self.history_consecutive_failures = 0
        self.history_rescue_suspended = False
        self.last_history_scan = {
            "source": None,
            "status": None,
            "message_count": 0,
            "allowed_count": 0,
            "handled_count": 0,
            "error_type": None,
            "attempt_epoch": 0,
            "current_response_index": 0,
            "current_action": "",
            "retry_count": 0,
            "retry_budget_remaining": 0,
            "retry_pending": False,
        }
        self._retry_task: asyncio.Task | None = None
        self._handling_startup_history = False
        self._final_state_logged = False
        self.attempt_epoch = 0
        self.stale_callback_texts = 0
        self._last_response_action_should_advance = True

    def _retry_budget_remaining(self) -> int:
        return max(self.max_inline_retries - self.retry_count, 0)

    def _finish(self, status: EventRunStatus, message: str = "") -> None:
        if self.finished.is_set():
            return
        self.result = EventRunResult(status=status, message=message)
        self.finished.set()

    def _text_matches(self, text: str, keywords: Iterable[str]) -> str | None:
        normalized_text = clean_text_for_match(text)
        if not normalized_text:
            return None
        for keyword in keywords:
            normalized_keyword = clean_text_for_match(keyword)
            if normalized_keyword and normalized_keyword in normalized_text:
                return keyword
        return None

    def _classify_text(
        self,
        text: str,
        *,
        source: str = "",
        message_id: int | None = None,
    ) -> bool:
        if not text or not self.spec.requires_result:
            return False
        match_meta = {
            "chat_id": self.chat.chat_id,
            "source": source,
            "message_id": message_id,
            **self._hard_timeout_context_meta(),
        }
        if keyword := self._text_matches(text, self.spec.success_keywords):
            self.log(
                f"事件引擎命中结果关键字: {keyword}",
                level="success",
                stage="result",
                event="event_engine_success_matched",
                meta=match_meta | {"keyword": keyword},
            )
            self._finish(EventRunStatus.SUCCESS, f"matched success keyword: {keyword}")
            return True
        return False

    async def _handle_callback_text(
        self,
        text: str,
        *,
        chat_id=None,
        message_id=None,
        attempt_epoch: int | None = None,
    ) -> None:
        if not text:
            return
        if attempt_epoch is not None and attempt_epoch != self.attempt_epoch:
            self.stale_callback_texts += 1
            self.log(
                "事件引擎跳过旧尝试按钮弹窗文本",
                stage="result",
                event="event_engine_stale_callback_text_skipped",
                visible=False,
                meta={
                    "chat_id": chat_id or self.chat.chat_id,
                    "message_id": message_id,
                    "callback_attempt_epoch": attempt_epoch,
                    "current_attempt_epoch": self.attempt_epoch,
                    "stale_callback_texts": self.stale_callback_texts,
                },
            )
            return
        if self.finished.is_set():
            self.log(
                "事件引擎已结束，跳过晚到按钮弹窗文本",
                stage="result",
                event="event_engine_callback_text_skipped_after_finished",
                visible=False,
                meta={
                    "chat_id": chat_id or self.chat.chat_id,
                    "message_id": message_id,
                    "attempt_epoch": self.attempt_epoch,
                    "status": self.result.status.value if self.result else "",
                },
            )
            return
        self.log(
            f"事件引擎处理按钮弹窗: {text}",
            stage="result",
            event="event_engine_callback_text_received",
            meta={
                "chat_id": chat_id or self.chat.chat_id,
                "message_id": message_id,
                "attempt_epoch": self.attempt_epoch,
            },
        )
        self._classify_text(
            text,
            source="callback_text",
            message_id=message_id,
        )

    def _schedule_retry(
        self,
        reason: str,
        *,
        source: str = "",
        message_id: int | None = None,
        trigger: str = "",
    ) -> None:
        retry_trigger_meta = {
            "retry_source": source,
            "retry_message_id": message_id,
            "retry_trigger": trigger,
        }
        if self.finished.is_set():
            self.log(
                f"事件引擎已结束，忽略晚到重试信号: {reason}",
                level="WARNING",
                stage="action",
                event="event_engine_retry_skipped_after_finished",
                meta={
                    "chat_id": self.chat.chat_id,
                    "reason": reason,
                    "finished": True,
                    "status": self.result.status.value if self.result else "",
                    "retry_count": self.retry_count,
                    "max_inline_retries": self.max_inline_retries,
                    "retry_budget_remaining": self._retry_budget_remaining(),
                    **retry_trigger_meta,
                    **self._retry_context_meta(retry_pending=False),
                },
            )
            return
        if self._retry_task and not self._retry_task.done():
            self.retry_suppressed_count += 1
            self.log(
                f"事件引擎已有重试任务运行中，忽略重复重试信号: {reason}",
                level="WARNING",
                stage="action",
                event="event_engine_retry_suppressed",
                meta={
                    "chat_id": self.chat.chat_id,
                    "reason": reason,
                    "retry_count": self.retry_count,
                    "max_inline_retries": self.max_inline_retries,
                    "retry_budget_remaining": self._retry_budget_remaining(),
                    "suppressed_count": self.retry_suppressed_count,
                    **retry_trigger_meta,
                    **self._retry_context_meta(retry_pending=True),
                },
            )
            return
        self.retry_count += 1
        if self.retry_count > self.max_inline_retries:
            self.log(
                f"事件引擎内部重试次数耗尽: {reason}",
                level="ERROR",
                stage="result",
                event="event_engine_retry_limit_exceeded",
                meta={
                    "chat_id": self.chat.chat_id,
                    "retry_count": self.retry_count,
                    "max_inline_retries": self.max_inline_retries,
                    "retry_budget_remaining": self._retry_budget_remaining(),
                    "reason": reason,
                    **retry_trigger_meta,
                    **self._retry_context_meta(retry_pending=False),
                },
            )
            self._finish(EventRunStatus.FAILED, f"retry limit exceeded: {reason}")
            return
        self.current_response_index = 0
        self._reset_attempt_state()
        self.log(
            f"事件引擎准备重试入口动作: {reason}",
            level="WARNING",
            stage="action",
            event="event_engine_retry_scheduled",
            meta={
                "chat_id": self.chat.chat_id,
                "reason": reason,
                    "retry_count": self.retry_count,
                    "max_inline_retries": self.max_inline_retries,
                    "retry_budget_remaining": self._retry_budget_remaining(),
                    **retry_trigger_meta,
                    **self._retry_context_meta(retry_pending=True),
                },
            )
        self._retry_task = asyncio.create_task(
            self._retry_initial_actions(reason, trigger_meta=retry_trigger_meta)
        )

    def _reset_attempt_state(self) -> None:
        previous_attempt_epoch = self.attempt_epoch
        cleared_processed_versions = len(self.processed_versions)
        cleared_sent_captcha_versions = len(self.sent_captcha_versions)
        cleared_clicked_versions = len(self.clicked_versions)
        cleared_history_duplicates = len(self.history_duplicate_versions)
        cleared_history_filtered = len(self.history_filtered_versions)
        cleared_history_unhandled = len(self.history_unhandled_versions)
        cleared_history_unhandled_duplicates = len(self.history_unhandled_duplicate_versions)
        cleared_history_tracked_message_ids = len(self.history_rescue_tracked_message_ids)
        self.attempt_epoch += 1
        self.processed_versions.clear()
        self.sent_captcha_versions.clear()
        self.clicked_versions.clear()
        self.history_duplicate_versions.clear()
        self.history_filtered_versions.clear()
        self.history_unhandled_versions.clear()
        self.history_unhandled_duplicate_versions.clear()
        self.history_rescue_tracked_message_ids.clear()
        self.log(
            "事件引擎重置尝试状态",
            stage="message",
            event="event_engine_attempt_state_reset",
            visible=False,
            meta={
                "chat_id": self.chat.chat_id,
                "previous_attempt_epoch": previous_attempt_epoch,
                "attempt_epoch": self.attempt_epoch,
                "retry_count": self.retry_count,
                "max_inline_retries": self.max_inline_retries,
                "retry_budget_remaining": self._retry_budget_remaining(),
                "cleared_processed_versions": cleared_processed_versions,
                "cleared_sent_captcha_versions": cleared_sent_captcha_versions,
                "cleared_clicked_versions": cleared_clicked_versions,
                "cleared_history_duplicates": cleared_history_duplicates,
                "cleared_history_filtered": cleared_history_filtered,
                "cleared_history_unhandled": cleared_history_unhandled,
                "cleared_history_unhandled_duplicates": cleared_history_unhandled_duplicates,
                "cleared_history_tracked_message_ids": cleared_history_tracked_message_ids,
            },
        )

    def _mark_message_processed_for_attempt(self, version, attempt_epoch: int) -> bool:
        if self.attempt_epoch != attempt_epoch:
            self.stale_attempt_versions.add(version)
            self.log(
                "事件引擎跳过旧尝试消息处理标记",
                stage="message",
                event="event_engine_stale_attempt_processed_mark_skipped",
                visible=False,
                meta={
                    "chat_id": self.chat.chat_id,
                    "message_version_hash": self._message_version_hash(version),
                    "message_attempt_epoch": attempt_epoch,
                    "current_attempt_epoch": self.attempt_epoch,
                    "stale_attempt_versions": len(self.stale_attempt_versions),
                },
            )
            return False
        self.processed_versions.add(version)
        return True

    def _current_response_action(self):
        if self.current_response_index >= len(self.spec.response_actions):
            return None
        return self.spec.response_actions[self.current_response_index]

    def _can_handle_action_from_startup_history(self, action) -> bool:
        return isinstance(action, ReplyByImageRecognitionAction)

    def _startup_history_skip_relevant(self, action, message: Message) -> bool:
        if isinstance(action, ClickKeyboardByTextAction):
            target = clean_text_for_match(action.text)
            return bool(target and any(target in clean_text_for_match(button) for button in _extract_button_texts(message)))
        if isinstance(action, ChooseOptionByImageAction):
            return bool(message.photo and _extract_button_texts(message))
        if isinstance(action, ReplyByCalculationProblemAction):
            return bool(get_message_text_content(message))
        if isinstance(action, (ClickButtonByCalculationProblemAction, ClickButtonByPoetryFillAction)):
            return bool(get_message_text_content(message) and _extract_button_texts(message))
        return True

    def _advance_response_action(
        self,
        *,
        action=None,
        message: Message | None = None,
        source: str,
        reason: str,
    ) -> bool:
        if self.current_response_index >= len(self.spec.response_actions):
            return False
        before_index = self.current_response_index
        action = action if action is not None else self.spec.response_actions[before_index]
        self.current_response_index += 1
        next_action = self._current_response_action()
        self.log(
            "事件引擎响应动作已推进",
            stage="action",
            event="event_engine_response_action_advanced",
            visible=False,
            meta={
                "chat_id": self.chat.chat_id,
                "message_id": getattr(message, "id", None) if message is not None else None,
                "action": str(action),
                "next_action": str(next_action) if next_action is not None else None,
                "from_index": before_index,
                "to_index": self.current_response_index,
                "response_action_count": len(self.spec.response_actions),
                "source": source,
                "reason": reason,
                "attempt_epoch": self.attempt_epoch,
                "retry_count": self.retry_count,
                "retry_budget_remaining": self._retry_budget_remaining(),
            },
        )
        return True

    def _log_response_action_not_advanced(
        self,
        *,
        action,
        message: Message,
        source: str,
        reason: str,
    ) -> None:
        next_action = self._current_response_action()
        self.log(
            "事件引擎响应动作已处理但未推进",
            stage="action",
            event="event_engine_response_action_not_advanced",
            visible=False,
            meta={
                "chat_id": self.chat.chat_id,
                "message_id": getattr(message, "id", None),
                "action": str(action),
                "next_action": str(next_action) if next_action is not None else None,
                "current_response_index": self.current_response_index,
                "response_action_count": len(self.spec.response_actions),
                "source": source,
                "reason": reason,
                "finished": self.finished.is_set(),
                "retry_pending": bool(self._retry_task and not self._retry_task.done()),
                "attempt_epoch": self.attempt_epoch,
                "retry_count": self.retry_count,
                "retry_budget_remaining": self._retry_budget_remaining(),
            },
        )

    def _finish_if_no_result_required(self) -> None:
        if self.spec.requires_result or self.finished.is_set():
            return
        if self.current_response_index < len(self.spec.response_actions):
            return
        self.log(
            "事件引擎动作已完成，无需等待结果断言",
            level="success",
            stage="result",
            event="event_engine_completed_without_result_assertion",
            meta={"chat_id": self.chat.chat_id},
        )
        self._finish(EventRunStatus.SUCCESS, "completed without result assertion")

    def _response_action_finished_skip(self, message: Message, *, source: str) -> bool:
        if not self.finished.is_set():
            return False
        action = self._current_response_action()
        self.log(
            "事件引擎已结束，跳过晚到响应动作副作用",
            stage="action",
            event="event_engine_response_action_skipped_after_finished",
            visible=False,
            meta={
                "chat_id": message.chat.id,
                "message_id": getattr(message, "id", None),
                "source": source,
                "status": self.result.status.value if self.result else "",
                "current_response_index": self.current_response_index,
                "current_action": str(action) if action is not None else "",
            },
        )
        return True

    def _callback_budget_kwargs(self) -> dict:
        kwargs = {}
        if self.callback_timeout_configured:
            kwargs["callback_timeout"] = self.callback_timeout
        if self.callback_retries_configured:
            kwargs["callback_retries"] = self.callback_retries
        return kwargs

    def _callback_operation_timeout(self) -> float:
        retry_wait_budget = max(self.callback_retries - 1, 0)
        callback_budget = (self.callback_timeout * self.callback_retries) + retry_wait_budget + 0.05
        return min(self.action_timeout, max(callback_budget, self.callback_timeout))

    def _retry_context_meta(self, *, retry_pending: bool) -> dict:
        action = self._current_response_action()
        return {
            "attempt_epoch": self.attempt_epoch,
            "current_response_index": self.current_response_index,
            "current_action": str(action) if action is not None else "",
            "retry_count": self.retry_count,
            "retry_budget_remaining": self._retry_budget_remaining(),
            "retry_pending": retry_pending,
        }

    def _callback_context_meta(self) -> dict:
        return self._retry_context_meta(
            retry_pending=bool(self._retry_task and not self._retry_task.done())
        )

    def _hard_timeout_context_meta(self) -> dict:
        action = self._current_response_action()
        return {
            "attempt_epoch": self.attempt_epoch,
            "current_response_index": self.current_response_index,
            "current_action": str(action) if action is not None else "",
            "retry_count": self.retry_count,
            "retry_budget_remaining": self._retry_budget_remaining(),
            "retry_pending": bool(self._retry_task and not self._retry_task.done()),
        }

    def _log_button_callback_exception(
        self,
        *,
        message: Message,
        button_text: str,
        source: str,
        trusted_timeout: bool,
        operation_timeout: float,
        exc: BaseException,
    ) -> None:
        context = self._callback_context_meta()
        self.log(
            f"事件引擎按钮回调异常: [{button_text}] {exc}",
            level="WARNING",
            stage="action",
            event="event_engine_button_callback_exception",
            meta={
                "chat_id": message.chat.id,
                "message_id": message.id,
                "button_text": button_text,
                "source": source,
                "trusted_timeout": trusted_timeout,
                "callback_timeout": self.callback_timeout,
                "callback_retries": self.callback_retries,
                "operation_timeout": operation_timeout,
                "error_type": type(exc).__name__,
                "attempt_epoch": context["attempt_epoch"],
                "current_response_index": context["current_response_index"],
                "current_action": context["current_action"],
                "retry_count": context["retry_count"],
                "retry_budget_remaining": context["retry_budget_remaining"],
                "retry_pending": context["retry_pending"],
            },
        )

    def _log_button_callback_unconfirmed(
        self,
        *,
        message: Message,
        button_text: str,
        source: str,
        callback_result: CallbackAnswerResult,
    ) -> None:
        context = self._callback_context_meta()
        self.log(
            f"事件引擎按钮回调未确认，允许后续重试: [{button_text}]",
            level="WARNING",
            stage="action",
            event="event_engine_button_callback_unconfirmed",
            meta={
                "chat_id": message.chat.id,
                "message_id": message.id,
                "button_text": button_text,
                "source": source,
                "attempt_epoch": context["attempt_epoch"],
                "current_response_index": context["current_response_index"],
                "current_action": context["current_action"],
                "retry_count": context["retry_count"],
                "retry_budget_remaining": context["retry_budget_remaining"],
                "retry_pending": context["retry_pending"],
                "callback_status": callback_result.status,
                "callback_reason": callback_result.reason,
                "callback_attempt": callback_result.attempt,
                "callback_max_retries": callback_result.max_retries,
                "callback_timeout": callback_result.timeout,
                "callback_error_type": callback_result.error_type,
                "callback_had_timeout": callback_result.had_timeout,
            },
        )

    def _record_button_callback_released_for_retry(
        self,
        *,
        message: Message,
        button_text: str,
        source: str,
        callback_result: CallbackAnswerResult,
    ) -> None:
        context = self._callback_context_meta()
        self.log(
            "事件引擎已释放未确认按钮点击版本，允许后续重试",
            level="WARNING",
            stage="action",
            event=EVENT_ENGINE_BUTTON_CALLBACK_RELEASED_FOR_RETRY,
            meta={
                "chat_id": message.chat.id,
                "message_id": message.id,
                "button_text": button_text,
                "source": source,
                "attempt_epoch": context["attempt_epoch"],
                "current_response_index": context["current_response_index"],
                "current_action": context["current_action"],
                "retry_count": context["retry_count"],
                "retry_budget_remaining": context["retry_budget_remaining"],
                "retry_pending": context["retry_pending"],
                "callback_status": callback_result.status,
                "callback_attempt": callback_result.attempt,
                "callback_max_retries": callback_result.max_retries,
                "callback_timeout": callback_result.timeout,
                "callback_had_timeout": callback_result.had_timeout,
                "clicked_versions": len(self.clicked_versions),
                "released_for_retry": True,
            },
        )

    def _consume_late_task_result(self, done_task: asyncio.Task, *, operation: str, meta: dict) -> None:
        try:
            exc = done_task.exception()
        except asyncio.CancelledError:
            self.log(
                "事件引擎硬超时后台任务已取消",
                stage="action",
                event=EVENT_ENGINE_HARD_TIMEOUT_LATE_CANCELLED,
                visible=False,
                meta=meta | {"operation": operation},
            )
        except Exception:
            self.log(
                "事件引擎硬超时后台任务异常结束",
                level="WARNING",
                stage="action",
                event=EVENT_ENGINE_HARD_TIMEOUT_LATE_EXCEPTION,
                meta=meta | {"operation": operation, "error_type": "Exception"},
            )
        else:
            if exc is not None:
                self.log(
                    f"事件引擎硬超时后台任务晚到异常: {exc}",
                    level="WARNING",
                    stage="action",
                    event=EVENT_ENGINE_HARD_TIMEOUT_LATE_EXCEPTION,
                    meta=meta | {"operation": operation, "error_type": type(exc).__name__},
                )
            else:
                self.log(
                    "事件引擎硬超时后台任务晚到完成",
                    stage="action",
                    event=EVENT_ENGINE_HARD_TIMEOUT_LATE_COMPLETED,
                    visible=False,
                    meta=meta | {"operation": operation},
                )

    async def _request_button_callback(
        self,
        *,
        message: Message,
        callback_data,
        trusted_timeout: bool,
        button_text: str,
        source: str,
    ) -> CallbackAnswerResult:
        operation_timeout = self._callback_operation_timeout()
        attempt_epoch = self.attempt_epoch
        callback_task = asyncio.create_task(
            self.request_callback_answer(
                self.app,
                message.chat.id,
                message.id,
                callback_data,
                trust_consumed_after_timeout=trusted_timeout,
                callback_text_handler=lambda text, **kwargs: self._handle_callback_text(
                    text,
                    attempt_epoch=attempt_epoch,
                    **kwargs,
                ),
                **self._callback_budget_kwargs(),
            )
        )
        try:
            done, _ = await asyncio.wait(
                {callback_task},
                timeout=operation_timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
        except asyncio.CancelledError:
            if not callback_task.done():
                callback_task.cancel()
                callback_task.add_done_callback(
                    lambda done_task: self._consume_late_task_result(
                        done_task,
                        operation="callback",
                        meta={
                            "chat_id": message.chat.id,
                            "message_id": message.id,
                            "source": source,
                            "timeout": operation_timeout,
                            "timeout_scope": "callback",
                            "cancelled_by_parent": True,
                            **self._hard_timeout_context_meta(),
                        },
                    )
                )
            raise
        try:
            if callback_task in done:
                return self._normalize_callback_result(await callback_task)
            callback_task.cancel()
            callback_task.add_done_callback(
                lambda done_task: self._consume_late_task_result(
                    done_task,
                    operation="callback",
                    meta={
                        "chat_id": message.chat.id,
                        "message_id": message.id,
                        "source": source,
                        "timeout": operation_timeout,
                        "timeout_scope": "callback",
                        **self._hard_timeout_context_meta(),
                    },
                )
            )
            raise EventHardTimeoutError("callback", operation_timeout)
        except (TimeoutError, asyncio.TimeoutError) as e:
            if callback_task.done() and not callback_task.cancelled():
                callback_exc = callback_task.exception()
                if callback_exc is not None:
                    self._log_button_callback_exception(
                        message=message,
                        button_text=button_text,
                        source=source,
                        trusted_timeout=trusted_timeout,
                        operation_timeout=operation_timeout,
                        exc=callback_exc,
                    )
                    raise callback_exc
            context = self._callback_context_meta()
            self.log(
                f"事件引擎按钮回调外层超时: [{button_text}]",
                level="WARNING",
                stage="action",
                event="event_engine_button_callback_outer_timeout",
                meta={
                    "chat_id": message.chat.id,
                    "message_id": message.id,
                    "button_text": button_text,
                    "source": source,
                    "trusted_timeout": trusted_timeout,
                    "callback_timeout": self.callback_timeout,
                    "callback_retries": self.callback_retries,
                    "timeout_scope": "callback",
                    "operation_timeout": operation_timeout,
                    "error_type": _retryable_error_type(e),
                    "attempt_epoch": context["attempt_epoch"],
                    "current_response_index": context["current_response_index"],
                    "current_action": context["current_action"],
                    "retry_count": context["retry_count"],
                    "retry_budget_remaining": context["retry_budget_remaining"],
                    "retry_pending": context["retry_pending"],
                },
            )
            return CallbackAnswerResult(
                confirmed=trusted_timeout,
                status="trusted_timeout" if trusted_timeout else "timeout_failed",
                reason=str(e),
                attempt=0,
                max_retries=self.callback_retries,
                timeout=self.callback_timeout,
                error_type=_retryable_error_type(e),
                had_timeout=True,
                trusted_consumed=trusted_timeout,
            )
        except errors.RPCError as e:
            self._log_button_callback_exception(
                message=message,
                button_text=button_text,
                source=source,
                trusted_timeout=trusted_timeout,
                operation_timeout=operation_timeout,
                exc=e,
            )
            raise

    async def _click_button(self, message: Message, target_text: str, *, trusted_timeout: bool = True) -> bool:
        reply_markup = message.reply_markup
        target = clean_text_for_match(target_text)
        if not target:
            return False
        if isinstance(reply_markup, InlineKeyboardMarkup):
            for row in reply_markup.inline_keyboard:
                for button in row:
                    button_text = getattr(button, "text", "") or ""
                    if target not in clean_text_for_match(button_text):
                        continue
                    callback_data = getattr(button, "callback_data", None)
                    if callback_data is None:
                        self.log(
                            f"事件引擎跳过无回调数据按钮: [{button_text}]",
                            level="WARNING",
                            stage="action",
                            event="event_engine_button_without_callback_data",
                            meta={
                                "chat_id": message.chat.id,
                                "message_id": message.id,
                                "button_text": button_text,
                            },
                        )
                        continue
                    version = (
                        message_version(message),
                        target,
                        button_text,
                        callback_data,
                    )
                    if version in self.clicked_versions:
                        self._record_button_click_duplicate(
                            message,
                            button_text=button_text,
                            source="startup_history" if self._handling_startup_history else "realtime",
                        )
                        return False
                    self.clicked_versions.add(version)
                    self.log(
                        f"事件引擎点击按钮: [{button_text}]",
                        stage="action",
                        event="event_engine_button_clicked",
                        meta={"chat_id": message.chat.id, "message_id": message.id, "button_text": button_text},
                    )
                    try:
                        callback_result = await self._request_button_callback(
                            message=message,
                            callback_data=callback_data,
                            trusted_timeout=trusted_timeout,
                            button_text=button_text,
                            source="startup_history" if self._handling_startup_history else "realtime",
                        )
                    except asyncio.CancelledError:
                        self.clicked_versions.discard(version)
                        raise
                    except (TimeoutError, asyncio.TimeoutError, errors.RPCError):
                        self.clicked_versions.discard(version)
                        raise
                    self._record_callback_result(
                        callback_result,
                        message=message,
                        button_text=button_text,
                        source="startup_history" if self._handling_startup_history else "realtime",
                    )
                    if not callback_result.confirmed:
                        self._log_button_callback_unconfirmed(
                            message=message,
                            button_text=button_text,
                            source="startup_history" if self._handling_startup_history else "realtime",
                            callback_result=callback_result,
                        )
                        self.clicked_versions.discard(version)
                        self._record_button_callback_released_for_retry(
                            message=message,
                            button_text=button_text,
                            source="startup_history" if self._handling_startup_history else "realtime",
                            callback_result=callback_result,
                        )
                    return callback_result.confirmed
        elif isinstance(reply_markup, ReplyKeyboardMarkup):
            for row in reply_markup.keyboard:
                for button in row:
                    button_text = getattr(button, "text", "") or ""
                    if target not in clean_text_for_match(button_text):
                        continue
                    version = (message_version(message), target, button_text)
                    if version in self.clicked_versions:
                        self._record_button_click_duplicate(
                            message,
                            button_text=button_text,
                            source="reply_keyboard",
                        )
                        return False
                    self.clicked_versions.add(version)
                    self.log(
                        f"事件引擎发送回复键盘文本: [{button_text}]",
                        stage="action",
                        event="event_engine_reply_keyboard_sent",
                        meta={"chat_id": message.chat.id, "message_id": message.id, "button_text": button_text},
                    )
                    try:
                        await self._send_response_message(
                            message,
                            button_text,
                            source="reply_keyboard",
                        )
                    except asyncio.CancelledError:
                        self.clicked_versions.discard(version)
                        raise
                    except (TimeoutError, asyncio.TimeoutError, errors.RPCError):
                        self.clicked_versions.discard(version)
                        raise
                    return True
        return False

    async def _choose_option_by_image(self, message: Message) -> bool:
        reply_markup = message.reply_markup
        if not (message.photo and isinstance(reply_markup, InlineKeyboardMarkup)):
            return False
        buttons = []
        for row in reply_markup.inline_keyboard:
            for button in row:
                button_text = getattr(button, "text", "") or ""
                if not button_text:
                    continue
                if getattr(button, "callback_data", None) is None:
                    self.log(
                        f"事件引擎跳过无回调数据图片选项按钮: [{button_text}]",
                        level="WARNING",
                        stage="action",
                        event="event_engine_button_without_callback_data",
                        meta={
                            "chat_id": message.chat.id,
                            "message_id": message.id,
                            "button_text": button_text,
                            "source": "image_option",
                        },
                    )
                    continue
                buttons.append(button)
        if not buttons:
            return False
        image_buffer = await self._download_message_media(message, source="image_option")
        image_buffer.seek(0)
        image_bytes = image_buffer.read()
        options = [button.text for button in buttons]
        tools = await self._get_ai_tools_with_timeout(message, source="image_option")
        result_index = await self._call_ai_tool(
            message,
            "image_option",
            tools.choose_option_by_image(
                image_bytes,
                "选择正确的选项",
                list(enumerate(options, start=1)),
            ),
        )
        if self._response_action_finished_skip(message, source="image_option"):
            return True
        if (
            isinstance(result_index, bool)
            or not isinstance(result_index, int)
            or not 1 <= result_index <= len(buttons)
        ):
            self.log(
                f"事件引擎 AI 返回非法选项序号: {result_index}",
                level="WARNING",
                stage="action",
                event="event_engine_invalid_option_index",
                meta={
                    "chat_id": message.chat.id,
                    "message_id": message.id,
                    "result_index": result_index,
                    "option_count": len(buttons),
                },
            )
            return False
        button = buttons[result_index - 1]
        version = (
            message_version(message),
            "image_option",
            button.text,
            button.callback_data,
        )
        if version in self.clicked_versions:
            self._record_button_click_duplicate(
                message,
                button_text=button.text,
                source="image_option",
            )
            return False
        self.clicked_versions.add(version)
        self.log(
            f"事件引擎选择图片选项: {button.text}",
            stage="action",
            event="event_engine_image_option_selected",
            meta={"chat_id": message.chat.id, "message_id": message.id, "result": button.text},
        )
        try:
            callback_result = await self._request_button_callback(
                message=message,
                callback_data=button.callback_data,
                trusted_timeout=False,
                button_text=button.text,
                source="image_option",
            )
        except asyncio.CancelledError:
            self.clicked_versions.discard(version)
            raise
        except (TimeoutError, asyncio.TimeoutError, errors.RPCError):
            self.clicked_versions.discard(version)
            raise
        self._record_callback_result(
            callback_result,
            message=message,
            button_text=button.text,
            source="image_option",
        )
        if not callback_result.confirmed:
            self._log_button_callback_unconfirmed(
                message=message,
                button_text=button.text,
                source="image_option",
                callback_result=callback_result,
            )
            self.clicked_versions.discard(version)
            self._record_button_callback_released_for_retry(
                message=message,
                button_text=button.text,
                source="image_option",
                callback_result=callback_result,
            )
        return callback_result.confirmed

    async def _reply_image_captcha(self, message: Message) -> bool:
        if not message.photo:
            return False
        if self.spec.image_caption_patterns:
            caption = message.caption or ""
            if not any(re.search(pattern, caption) for pattern in self.spec.image_caption_patterns):
                return False
        version = message_version(message)
        if version in self.sent_captcha_versions:
            return False
        self.sent_captcha_versions.add(version)
        try:
            image_buffer = await self._download_message_media(message, source="captcha")
        except asyncio.CancelledError:
            self.sent_captcha_versions.discard(version)
            raise
        except (TimeoutError, asyncio.TimeoutError, errors.RPCError):
            self.sent_captcha_versions.discard(version)
            raise
        image_buffer.seek(0)
        image_bytes = image_buffer.read()
        tools = await self._get_ai_tools_with_timeout(message, source="captcha")
        try:
            raw_text = await self._call_ai_tool(
                message,
                "captcha",
                tools.extract_text_by_image(image_bytes),
            )
        except asyncio.CancelledError:
            self.sent_captcha_versions.discard(version)
            raise
        except (TimeoutError, asyncio.TimeoutError, errors.RPCError):
            self.sent_captcha_versions.discard(version)
            raise
        if self._classify_text(
            str(raw_text or ""),
            source="captcha_ocr",
            message_id=getattr(message, "id", None),
        ):
            self.captcha_result_text_preemptions += 1
            self.log(
                "事件引擎 OCR 结果命中签到状态，跳过验证码回复",
                level="success",
                stage="result",
                event=EVENT_ENGINE_CAPTCHA_RESULT_TEXT_PREEMPTED,
                meta={
                    "chat_id": message.chat.id,
                    "message_id": message.id,
                    "source": "captcha",
                },
            )
            return True
        text = clean_text_for_send(raw_text)
        text = text.translate(str.maketrans("", "", string.punctuation)).replace(" ", "")
        if self.spec.captcha_case == "upper":
            text = text.upper()
        elif self.spec.captcha_case == "lower":
            text = text.lower()
        if self.spec.captcha_charsets:
            allowed = set("".join(self.spec.captcha_charsets))
            text = "".join(char for char in text if char in allowed)
        if not text:
            self.log(
                "事件引擎 OCR 返回空验证码，准备重试入口动作",
                level="WARNING",
                stage="action",
                event="event_engine_empty_captcha_retry",
                meta={"chat_id": message.chat.id, "message_id": message.id},
            )
            self._schedule_retry(
                "empty captcha",
                source="captcha",
                message_id=getattr(message, "id", None),
                trigger="empty_captcha",
            )
            return True
        if self.spec.captcha_lengths and len(text) not in self.spec.captcha_lengths:
            self.log(
                f"事件引擎 OCR 验证码长度不匹配: {text}",
                level="WARNING",
                stage="action",
                event="event_engine_captcha_length_mismatch",
                meta={
                    "chat_id": message.chat.id,
                    "message_id": message.id,
                    "length": len(text),
                    "expected_lengths": self.spec.captcha_lengths,
                },
            )
            self._schedule_retry(
                "captcha length mismatch",
                source="captcha",
                message_id=getattr(message, "id", None),
                trigger="captcha_length_mismatch",
            )
            return True
        self.log(
            f"事件引擎识别验证码: {text}",
            stage="action",
            event="event_engine_captcha_recognized",
            meta={"chat_id": message.chat.id, "message_id": message.id},
        )
        try:
            await asyncio.sleep(random.uniform(1.5, 3.5))
        except asyncio.CancelledError:
            self.sent_captcha_versions.discard(version)
            raise
        if self.finished.is_set():
            self.sent_captcha_versions.discard(version)
            self.log(
                "事件引擎已结束，跳过晚到验证码回复",
                stage="action",
                event="event_engine_captcha_send_skipped_after_finished",
                meta={
                    "chat_id": message.chat.id,
                    "message_id": message.id,
                    "status": self.result.status.value if self.result else "",
                },
            )
            return True
        try:
            if self.spec.reply_captcha_to_message:
                sent = await self._send_response_message(
                    message,
                    text,
                    source="captcha",
                    reply_to_message_id=message.id,
                )
                reply_to_message = True
            else:
                sent = await self._send_response_message(message, text, source="captcha")
                reply_to_message = False
        except asyncio.CancelledError:
            self.sent_captcha_versions.discard(version)
            raise
        except (TimeoutError, asyncio.TimeoutError, errors.RPCError):
            self.sent_captcha_versions.discard(version)
            raise
        self.log(
            "事件引擎已发送验证码",
            stage="action",
            event="event_engine_captcha_sent",
            meta={
                "chat_id": message.chat.id,
                "message_id": getattr(sent, "id", None),
                "source_message_id": message.id,
                "reply_to_message": reply_to_message,
            },
        )
        return True

    async def _reply_calculation(self, message: Message) -> bool:
        text = get_message_text_content(message)
        if not text:
            return False
        tools = await self._get_ai_tools_with_timeout(message, source="calculation_reply")
        answer = (
            await self._call_ai_tool(
                message,
                "calculation_reply",
                tools.calculate_problem(text),
            )
            or ""
        ).strip()
        if self._response_action_finished_skip(message, source="calculation"):
            return True
        if not answer:
            return False
        self.log(
            f"事件引擎计算回答: {answer}",
            stage="action",
            event="event_engine_calculation_answered",
            meta={"chat_id": message.chat.id, "message_id": message.id},
        )
        await self._send_response_message(message, answer, source="calculation")
        return True

    async def _click_calculation_answer(self, message: Message) -> bool:
        text = get_message_text_content(message)
        if not text or not isinstance(message.reply_markup, InlineKeyboardMarkup):
            return False
        tools = await self._get_ai_tools_with_timeout(message, source="calculation_click")
        answer = (
            await self._call_ai_tool(
                message,
                "calculation_click",
                tools.calculate_problem(text),
            )
            or ""
        ).strip()
        if self._response_action_finished_skip(message, source="calculation_click"):
            return True
        if not answer:
            return False
        self.log(
            f"事件引擎计算并尝试点击答案: {answer}",
            stage="action",
            event="event_engine_calculation_click_answered",
            meta={"chat_id": message.chat.id, "message_id": message.id},
        )
        return await self._click_button(message, answer, trusted_timeout=False)

    async def _click_poetry_answer(self, message: Message) -> bool:
        text = get_message_text_content(message)
        options = extract_keyboard_options(message)
        if not text or not options:
            return False
        pending_blanks = _count_poetry_fill_blanks(text)
        tools = await self._get_ai_tools_with_timeout(message, source="poetry_click")
        answer = clean_text_for_send(
            await self._call_ai_tool(
                message,
                "poetry_click",
                tools.solve_poetry_fill(text, options),
            )
            or ""
        )
        if self._response_action_finished_skip(message, source="poetry_click"):
            return True
        if not answer:
            return False
        candidates = [answer]
        if len(answer) > 1:
            candidates.extend([char for char in answer if char.strip()])
        self.log(
            f"事件引擎填诗并尝试点击答案: {answer}",
            stage="action",
            event="event_engine_poetry_click_answered",
            meta={"chat_id": message.chat.id, "message_id": message.id},
        )
        for candidate in _dedupe(candidates):
            if await self._click_button(message, candidate, trusted_timeout=False):
                if pending_blanks > max(len(candidate), 1):
                    self._last_response_action_should_advance = False
                return True
        return False

    async def _send_with_timeout(
        self,
        sender,
        *args,
        timeout: float | None = None,
        meta: dict | None = None,
        **kwargs,
    ):
        send_meta = {"chat_id": args[0] if args else self.chat.chat_id}
        if meta:
            send_meta.update(meta)
        return await self._await_with_hard_timeout(
            sender(*args, **kwargs),
            timeout=timeout or self.send_timeout,
            operation="send",
            meta=send_meta,
        )

    async def _await_with_hard_timeout(self, awaitable, *, timeout: float, operation: str, meta: dict | None = None):
        timeout_meta = (
            {"timeout_scope": operation}
            | (meta or {})
            | self._hard_timeout_context_meta()
        )
        task = asyncio.create_task(awaitable)
        try:
            done, _ = await asyncio.wait({task}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            if not task.done():
                task.cancel()
                task.add_done_callback(
                    lambda done_task: self._consume_late_task_result(
                        done_task,
                        operation=operation,
                        meta=timeout_meta
                        | {
                            "timeout": timeout,
                            "timeout_scope": operation,
                            "cancelled_by_parent": True,
                        },
                    )
                )
            raise
        if task in done:
            return await task
        task.cancel()
        task.add_done_callback(
            lambda done_task: self._consume_late_task_result(
                done_task,
                operation=operation,
                meta=timeout_meta | {"timeout": timeout, "timeout_scope": operation},
            )
        )
        raise EventHardTimeoutError(operation, timeout)

    async def _download_message_media(self, message: Message, *, source: str):
        try:
            return await self._await_with_hard_timeout(
                self.app.download_media(message.photo.file_id, in_memory=True),
                timeout=self.media_timeout,
                operation="media",
                meta={
                    "chat_id": message.chat.id,
                    "message_id": getattr(message, "id", None),
                    "source": source,
                },
            )
        except (TimeoutError, asyncio.TimeoutError, errors.RPCError) as e:
            self.log(
                f"事件引擎媒体下载失败: {e}",
                level="WARNING",
                stage="action",
                event="event_engine_media_download_retryable_error",
                meta={
                    "chat_id": message.chat.id,
                    "message_id": getattr(message, "id", None),
                    "source": source,
                    "timeout_scope": getattr(e, "operation", "media"),
                    "error_type": _retryable_error_type(e),
                    "timeout": self.media_timeout,
                },
            )
            raise

    async def _call_ai_tool(self, message: Message, source: str, awaitable):
        try:
            return await self._await_with_hard_timeout(
                awaitable,
                timeout=self.ai_timeout,
                operation="ai",
                meta={
                    "chat_id": message.chat.id,
                    "message_id": getattr(message, "id", None),
                    "source": source,
                },
            )
        except (TimeoutError, asyncio.TimeoutError, errors.RPCError) as e:
            self.log(
                f"事件引擎 AI 调用失败: {e}",
                level="WARNING",
                stage="action",
                event="event_engine_ai_retryable_error",
                meta={
                    "chat_id": message.chat.id,
                    "message_id": getattr(message, "id", None),
                    "source": source,
                    "timeout_scope": getattr(e, "operation", "ai"),
                    "error_type": _retryable_error_type(e),
                    "timeout": self.ai_timeout,
                },
            )
            raise

    async def _get_ai_tools_with_timeout(self, message: Message, *, source: str):
        try:
            return await self._await_with_hard_timeout(
                asyncio.to_thread(self.get_ai_tools),
                timeout=self.ai_timeout,
                operation="ai_tools",
                meta={
                    "chat_id": message.chat.id,
                    "message_id": getattr(message, "id", None),
                    "source": source,
                },
            )
        except (TimeoutError, asyncio.TimeoutError, errors.RPCError) as e:
            self.log(
                f"事件引擎 AI 工具加载失败: {e}",
                level="WARNING",
                stage="action",
                event="event_engine_ai_retryable_error",
                meta={
                    "chat_id": message.chat.id,
                    "message_id": getattr(message, "id", None),
                    "source": source,
                    "operation": "ai_tools",
                    "timeout_scope": getattr(e, "operation", "ai_tools"),
                    "error_type": _retryable_error_type(e),
                    "timeout": self.ai_timeout,
                },
            )
            raise

    async def _send_response_message(
        self,
        message: Message,
        text: str,
        *,
        source: str,
        **kwargs,
    ):
        try:
            sent = await self._send_with_timeout(
                self.send_message,
                message.chat.id,
                text,
                timeout=self.send_timeout,
                meta={
                    "message_id": getattr(message, "id", None),
                    "source_message_id": getattr(message, "id", None),
                    "source": source,
                },
                **kwargs,
            )
            self._mark_entry_message_sent(sent)
            self.response_message_count += 1
            self.log(
                "事件引擎响应消息已发送",
                stage="action",
                event="event_engine_response_message_sent",
                visible=False,
                meta={
                    "chat_id": message.chat.id,
                    "message_id": getattr(sent, "id", None),
                    "source_message_id": getattr(message, "id", None),
                    "source": source,
                    "response_messages_sent": self.response_message_count,
                },
            )
            return sent
        except (TimeoutError, asyncio.TimeoutError, errors.RPCError, Exception) as e:
            self.log(
                f"事件引擎响应发送动作失败: {e}",
                level="WARNING",
                stage="action",
                event="event_engine_response_send_retryable_error",
                meta={
                    "chat_id": message.chat.id,
                    "message_id": getattr(message, "id", None),
                    "source_message_id": getattr(message, "id", None),
                    "source": source,
                    "timeout_scope": getattr(e, "operation", "send"),
                    "error_type": _retryable_error_type(e),
                    "timeout": self.send_timeout,
                },
            )
            raise

    async def _wait_action(self, action: WaitAction) -> bool:
        self.log(
            f"等待 {action.seconds} 秒",
            stage="action",
            event="event_engine_wait_started",
            meta={"chat_id": self.chat.chat_id, "seconds": action.seconds},
        )
        try:
            await asyncio.wait_for(self.finished.wait(), timeout=action.seconds)
            return False
        except asyncio.TimeoutError:
            self._completed_wait_seconds += action.seconds
            self.log(
                f"等待完成（{action.seconds} 秒）",
                stage="action",
                event="event_engine_wait_completed",
                meta={"chat_id": self.chat.chat_id, "seconds": action.seconds},
            )
            return not self.finished.is_set()

    async def _send_initial_actions(self, *, retry: bool = False) -> None:
        for index, action in enumerate(self.spec.send_actions, start=1):
            if retry and index == 1:
                await asyncio.sleep(self.retry_wait)
            if self.finished.is_set():
                return
            try:
                if isinstance(action, WaitAction):
                    if not await self._wait_action(action):
                        return
                elif isinstance(action, SendTextAction):
                    self.log(
                        f"事件引擎发送入口文本: {action.text}",
                        stage="action",
                        event="event_engine_send_text",
                        meta={"chat_id": self.chat.chat_id, "text": action.text, "retry": retry},
                    )
                    message = await self._send_with_timeout(
                        self.send_message,
                        self.chat.chat_id,
                        action.text,
                        self.chat.delete_after,
                        meta={
                            "source": "initial",
                            "action": str(action),
                            "retry": retry,
                        },
                    )
                    self._mark_entry_message_sent(message)
                elif isinstance(action, SendDiceAction):
                    self.log(
                        f"事件引擎发送入口骰子: {action.dice}",
                        stage="action",
                        event="event_engine_send_dice",
                        meta={"chat_id": self.chat.chat_id, "emoji": action.dice, "retry": retry},
                    )
                    message = await self._send_with_timeout(
                        self.send_dice,
                        self.chat.chat_id,
                        action.dice,
                        self.chat.delete_after,
                        meta={
                            "source": "initial",
                            "action": str(action),
                            "retry": retry,
                        },
                    )
                    self._mark_entry_message_sent(message)
            except (TimeoutError, asyncio.TimeoutError, errors.RPCError) as e:
                self.log(
                    f"事件引擎入口动作发送失败: {e}",
                    level="WARNING",
                    stage="action",
                    event="event_engine_initial_send_retryable_error",
                    meta={
                        "chat_id": self.chat.chat_id,
                        "action": str(action),
                        "source": "initial",
                        "operation": "send",
                        "timeout_scope": getattr(e, "operation", "send"),
                        "retry": retry,
                        "error_type": _retryable_error_type(e),
                        "timeout": self.send_timeout,
                    },
                )
                raise BusinessRetryableError(
                    f"Event engine initial action failed. chat_id={self.chat.chat_id}, action={action}"
                ) from e

    def _mark_entry_message_sent(self, message) -> None:
        message_id = getattr(message, "id", None)
        if isinstance(message_id, int):
            if self.history_rescue_min_message_id is None:
                self.history_rescue_min_message_id = message_id
            else:
                self.history_rescue_min_message_id = max(self.history_rescue_min_message_id, message_id)

    def _track_history_rescue_message(self, message: Message) -> None:
        message_id = getattr(message, "id", None)
        if isinstance(message_id, int):
            self.history_rescue_tracked_message_ids.add(message_id)

    async def _retry_initial_actions(self, reason: str, *, trigger_meta: dict | None = None) -> None:
        trigger_meta = trigger_meta or {}
        self.log(
            "事件引擎重试入口动作开始",
            stage="action",
            event="event_engine_retry_started",
            meta={
                "chat_id": self.chat.chat_id,
                "reason": reason,
                "retry_count": self.retry_count,
                "max_inline_retries": self.max_inline_retries,
                "retry_budget_remaining": self._retry_budget_remaining(),
                **trigger_meta,
                **self._retry_context_meta(retry_pending=True),
            },
        )
        try:
            async with self.message_lock:
                await self._send_initial_actions(retry=True)
                await self._drain_immediate_response_actions(ignore_retry_pending=True)
                self._finish_if_no_result_required()
            self.log(
                "事件引擎重试入口动作完成",
                level="success" if self.finished.is_set() else "INFO",
                stage="action",
                event="event_engine_retry_completed",
                meta={
                    "chat_id": self.chat.chat_id,
                    "reason": reason,
                    "retry_count": self.retry_count,
                    "max_inline_retries": self.max_inline_retries,
                    "retry_budget_remaining": self._retry_budget_remaining(),
                    "finished": self.finished.is_set(),
                    **trigger_meta,
                    **self._retry_context_meta(retry_pending=False),
                },
            )
        except BusinessRetryableError as e:
            self.log(
                f"事件引擎重试入口动作失败: {e}",
                level="ERROR",
                stage="action",
                event="event_engine_retry_initial_send_failed",
                meta={
                    "chat_id": self.chat.chat_id,
                    "reason": reason,
                    "retry_count": self.retry_count,
                    "max_inline_retries": self.max_inline_retries,
                    "retry_budget_remaining": self._retry_budget_remaining(),
                    **trigger_meta,
                    **self._retry_context_meta(retry_pending=False),
                },
            )
            self._finish(EventRunStatus.FAILED, str(e))
        except asyncio.CancelledError:
            self.log(
                "事件引擎重试入口动作被取消",
                level="WARNING",
                stage="action",
                event="event_engine_retry_cancelled",
                meta={
                    "chat_id": self.chat.chat_id,
                    "reason": reason,
                    "retry_count": self.retry_count,
                    "max_inline_retries": self.max_inline_retries,
                    "retry_budget_remaining": self._retry_budget_remaining(),
                    "finished": self.finished.is_set(),
                    **trigger_meta,
                    **self._retry_context_meta(retry_pending=False),
                },
            )
            raise
        except Exception as e:
            self.log(
                f"事件引擎重试入口动作异常: {e}",
                level="ERROR",
                stage="action",
                event="event_engine_retry_initial_send_error",
                meta={
                    "chat_id": self.chat.chat_id,
                    "reason": reason,
                    "retry_count": self.retry_count,
                    "max_inline_retries": self.max_inline_retries,
                    "retry_budget_remaining": self._retry_budget_remaining(),
                    "error_type": _retryable_error_type(e),
                    **trigger_meta,
                    **self._retry_context_meta(retry_pending=False),
                },
            )
            self._finish(EventRunStatus.FAILED, str(e))

    async def _drain_immediate_response_actions(self, *, ignore_retry_pending: bool = False) -> None:
        while not self.finished.is_set():
            if not ignore_retry_pending and self._retry_task and not self._retry_task.done():
                return
            action = self._current_response_action()
            if not isinstance(action, (SendTextAction, SendDiceAction, WaitAction)):
                return
            if self.finished.is_set():
                return
            try:
                if isinstance(action, WaitAction):
                    if not await self._wait_action(action):
                        return
                    message = None
                elif isinstance(action, SendTextAction):
                    self.log(
                        f"事件引擎发送后续文本: {action.text}",
                        stage="action",
                        event="event_engine_send_followup_text",
                        meta={"chat_id": self.chat.chat_id, "text": action.text},
                    )
                    message = await self._send_with_timeout(
                        self.send_message,
                        self.chat.chat_id,
                        action.text,
                        self.chat.delete_after,
                        meta={
                            "source": "followup",
                            "action": str(action),
                        },
                    )
                    self._mark_entry_message_sent(message)
                elif isinstance(action, SendDiceAction):
                    self.log(
                        f"事件引擎发送后续骰子: {action.dice}",
                        stage="action",
                        event="event_engine_send_followup_dice",
                        meta={"chat_id": self.chat.chat_id, "emoji": action.dice},
                    )
                    message = await self._send_with_timeout(
                        self.send_dice,
                        self.chat.chat_id,
                        action.dice,
                        self.chat.delete_after,
                        meta={
                            "source": "followup",
                            "action": str(action),
                        },
                    )
                    self._mark_entry_message_sent(message)
            except (TimeoutError, asyncio.TimeoutError, errors.RPCError) as e:
                self.log(
                    f"事件引擎后续发送动作失败: {e}",
                    level="WARNING",
                    stage="action",
                    event="event_engine_followup_send_retryable_error",
                    meta={
                        "chat_id": self.chat.chat_id,
                        "action": str(action),
                        "timeout_scope": getattr(e, "operation", "send"),
                        "error_type": _retryable_error_type(e),
                        "timeout": self.send_timeout,
                    },
                )
                self._schedule_retry(
                    f"followup send failed: {e}",
                    source="followup",
                    message_id=None,
                    trigger="followup_send_failed",
                )
                return
            self._advance_response_action(
                action=action,
                message=message,
                source="followup",
                reason="immediate_send_completed",
            )
            self._finish_if_no_result_required()

    async def handle_message(self, message: Message) -> None:
        if self.finished.is_set():
            self._record_message_skip("finished", message)
            return
        if not self._is_inbound_chat_message(message):
            self._record_message_skip("non_inbound", message)
            return
        # Terminal results must not queue behind sends/waits. Classification is
        # synchronous; only action execution/advancement needs the message lock.
        if self.spec.requires_result and self.message_lock.locked():
            version = message_version(message)
            if (
                version not in self.stale_attempt_versions
                and version not in self.processed_versions
                and version not in self.processing_versions
                and self._classify_text(
                    get_message_text_content(message),
                    source="realtime",
                    message_id=getattr(message, "id", None),
                )
            ):
                self._mark_message_processed_for_attempt(version, self.attempt_epoch)
                return
        async with self.message_lock:
            await self._handle_message_locked(message)

    async def _handle_message_locked(self, message: Message) -> None:
        if self.finished.is_set():
            self._record_message_skip("finished", message)
            return
        version = message_version(message)
        if version in self.stale_attempt_versions:
            self._record_message_skip("stale_attempt", message, version=version)
            return
        if version in self.processed_versions:
            self._record_message_skip("duplicate", message, version=version)
            return
        if version in self.processing_versions:
            self._record_message_skip("concurrent_duplicate", message, version=version)
            return
        attempt_epoch = self.attempt_epoch
        self.processing_versions.add(version)
        try:
            try:
                message_readable = readable_message(message)
            except Exception:
                message_readable = f"Message(id={getattr(message, 'id', None)})"
            self.log(
                f"事件引擎收到消息: {message_readable}",
                stage="message",
                event="event_engine_message_received",
                meta={"chat_id": message.chat.id, "message_id": message.id},
            )
            text = get_message_text_content(message)
            current_action = self._current_response_action()
            if self._classify_text(
                text,
                source="realtime",
                message_id=getattr(message, "id", None),
            ):
                self._mark_message_processed_for_attempt(version, attempt_epoch)
                return
            retry_pending = self._retry_task and not self._retry_task.done()
            if not retry_pending and await self._handle_current_response_action(message):
                if self._mark_message_processed_for_attempt(version, attempt_epoch):
                    self._track_history_rescue_message(message)
                return
            if await self._handle_unexpected_interaction(message):
                self._mark_message_processed_for_attempt(version, attempt_epoch)
                return
            self._record_message_unhandled(
                message,
                version=version,
                current_action=current_action,
                retry_pending=retry_pending,
            )
        except (TimeoutError, asyncio.TimeoutError, errors.RPCError) as e:
            context = self._hard_timeout_context_meta()
            self.log(
                f"事件引擎处理消息超时/Telegram 错误: {e}",
                level="WARNING",
                stage="action",
                event="event_engine_message_retryable_error",
                meta={
                    "chat_id": self.chat.chat_id,
                    "message_id": getattr(message, "id", None),
                    "error_type": _retryable_error_type(e),
                    "operation": getattr(e, "operation", "message"),
                    "timeout_scope": getattr(e, "operation", "message"),
                    "operation_timeout": getattr(e, "timeout", self.action_timeout),
                    "attempt_epoch": context["attempt_epoch"],
                    "current_response_index": context["current_response_index"],
                    "current_action": context["current_action"],
                    "retry_count": context["retry_count"],
                    "retry_budget_remaining": context["retry_budget_remaining"],
                    "retry_pending": context["retry_pending"],
                },
            )
            self._schedule_retry(
                f"retryable error: {e}",
                source="message",
                message_id=getattr(message, "id", None),
                trigger="message_retryable_error",
            )
        except asyncio.CancelledError:
            self._record_message_processing_cancelled(
                message,
                version=version,
                attempt_epoch=attempt_epoch,
            )
            raise
        except Exception as e:
            self.log(
                f"事件引擎处理消息失败: {e}",
                level="ERROR",
                stage="action",
                event="event_engine_message_error",
                meta={"chat_id": self.chat.chat_id, "message_id": getattr(message, "id", None), "error_type": _retryable_error_type(e)},
            )
            self._finish(EventRunStatus.FAILED, str(e))
        finally:
            self.processing_versions.discard(version)

    async def run(self) -> EventRunResult:
        self.log(
            "事件引擎开始执行",
            stage="action",
            event="event_engine_started",
            meta={"chat_id": self.chat.chat_id, "timeout": self.timeout},
        )
        try:
            history_handled = await self._walk_history()
            if self.finished.is_set():
                return self._complete_run("history")
            if not history_handled:
                async with self.message_lock:
                    await self._send_initial_actions()
                    await self._drain_immediate_response_actions()
                    self._finish_if_no_result_required()
                if self.finished.is_set():
                    return self._complete_run("initial_actions")
            try:
                # Reserve explicit wait time for the first attempt and inline retries.
                # RPC/action timeouts stay unchanged; waiting is not a failed RPC.
                wait_budget = action_wait_budget(
                    (action.dict() for action in self.chat.actions), self.max_inline_retries,
                )
                # Startup/entry waits happened before this timer. Subtract them
                # so the complete run fits the worker's shared wait allowance.
                effective_timeout = self.timeout + max(0, wait_budget - self._completed_wait_seconds)
                result = await asyncio.wait_for(self._wait_finished(), timeout=effective_timeout)
                self._log_final_state(result, source="wait_finished")
                return result
            except asyncio.TimeoutError:
                self._log_timeout_state()
                error = BusinessRetryableError(
                    f"Event engine timed out after {effective_timeout}s. chat_id={self.chat.chat_id}"
                )
                self._log_final_state(
                    EventRunResult(EventRunStatus.FAILED, str(error)),
                    source="timeout",
                )
                raise error
        except Exception as e:
            if not self._final_state_logged:
                self._log_final_state(
                    EventRunResult(EventRunStatus.FAILED, str(e) or _retryable_error_type(e)),
                    source="exception",
                )
            raise
        finally:
            if self._retry_task and not self._retry_task.done():
                self._retry_task.cancel()

    def _complete_run(self, source: str) -> EventRunResult:
        result = self.result or EventRunResult(EventRunStatus.FAILED, "missing result")
        self._log_final_state(result, source=source)
        return result

    async def _wait_finished(self) -> EventRunResult:
        while not self.finished.is_set():
            if self.history_limit > 0 and not self.history_rescue_suspended:
                now = asyncio.get_running_loop().time()
                if now - self._last_history_rescue_at >= self.history_rescue_interval:
                    self._last_history_rescue_at = now
                    await self._walk_history_rescue_until_finished()
            await asyncio.sleep(0.2)
        return self.result or EventRunResult(EventRunStatus.FAILED, "missing result")

    async def _walk_history_rescue_until_finished(self) -> bool:
        history_task = asyncio.create_task(self._walk_history(rescue=True))
        finished_task = asyncio.create_task(self.finished.wait())
        try:
            done, _ = await asyncio.wait(
                {history_task, finished_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if history_task in done:
                return await history_task
            history_task.cancel()
            try:
                await history_task
            except asyncio.CancelledError:
                pass
            self.log(
                "事件引擎任务已完成，取消运行期历史补漏",
                stage="message",
                event="event_engine_history_rescue_cancelled",
                visible=False,
                meta={
                    "chat_id": self.chat.chat_id,
                    "source": "rescue",
                    "status": "cancelled",
                    "cancelled_scans": self.history_scan_counts["cancelled"],
                    "scan_in_progress": self.history_scan_lock.locked(),
                    **self._hard_timeout_context_meta(),
                },
            )
            return False
        finally:
            if not finished_task.done():
                finished_task.cancel()
            await asyncio.gather(finished_task, return_exceptions=True)

    def _state_snapshot_meta(self) -> dict:
        action = self._current_response_action()
        return {
            "chat_id": self.chat.chat_id,
            "timeout": self.timeout,
            "current_response_index": self.current_response_index,
            "response_action_count": len(self.spec.response_actions),
            "current_action": str(action) if action is not None else None,
            "action_timeout": self.action_timeout,
            "send_timeout": self.send_timeout,
            "media_timeout": self.media_timeout,
            "ai_timeout": self.ai_timeout,
            "callback_timeout": self.callback_timeout,
            "callback_retries": self.callback_retries,
            "ai_fallback_enabled": self.ai_fallback_enabled,
            "retry_count": self.retry_count,
            "max_inline_retries": self.max_inline_retries,
            "retry_wait": self.retry_wait,
            "retry_budget_remaining": self._retry_budget_remaining(),
            "retry_suppressed_count": self.retry_suppressed_count,
            "retry_pending": bool(self._retry_task and not self._retry_task.done()),
            "attempt_epoch": self.attempt_epoch,
            "history_limit": self.history_limit,
            "history_rescue_interval": self.history_rescue_interval,
            "history_rpc_timeout": self.history_rpc_timeout,
            "history_result_max_age": self.history_result_max_age,
            "history_failure_threshold": self.history_failure_threshold,
            "history_consecutive_failures": self.history_consecutive_failures,
            "history_rescue_suspended": self.history_rescue_suspended,
            "history_rescue_min_message_id": self.history_rescue_min_message_id,
            "history_rescue_tracked_message_ids": len(self.history_rescue_tracked_message_ids),
            "history_startup_scans": self.history_scan_counts["startup"],
            "history_rescue_scans": self.history_scan_counts["rescue"],
            "history_failed_scans": self.history_scan_counts["failed"],
            "history_circuit_opened": self.history_scan_counts["circuit_opened"],
            "history_concurrent_skipped": self.history_scan_counts["concurrent_skipped"],
            "history_cancelled_scans": self.history_scan_counts["cancelled"],
            "history_scan_in_progress": self.history_scan_lock.locked(),
            "history_messages_seen": self.history_scan_counts["messages_seen"],
            "history_messages_allowed": self.history_scan_counts["messages_allowed"],
            "history_messages_handled": self.history_scan_counts["messages_handled"],
            "history_duplicate_messages": self.history_scan_counts["duplicates"],
            "history_tracked_rechecks": self.history_scan_counts["tracked_rechecks"],
            "history_expired_messages": self.history_scan_counts["expired"],
            "history_filtered_before_entry": self.history_scan_counts["filtered_before_entry"],
            "history_filtered_expired": self.history_scan_counts["filtered_expired"],
            "history_hard_failures_skipped": self.history_scan_counts["hard_failures_skipped"],
            "history_unhandled_duplicates": self.history_scan_counts["unhandled_duplicates"],
            "last_history_scan_source": self.last_history_scan["source"],
            "last_history_scan_status": self.last_history_scan["status"],
            "last_history_scan_message_count": self.last_history_scan["message_count"],
            "last_history_scan_allowed_count": self.last_history_scan["allowed_count"],
            "last_history_scan_handled_count": self.last_history_scan["handled_count"],
            "last_history_scan_error_type": self.last_history_scan["error_type"],
            "last_history_scan_attempt_epoch": self.last_history_scan["attempt_epoch"],
            "last_history_scan_current_response_index": self.last_history_scan[
                "current_response_index"
            ],
            "last_history_scan_current_action": self.last_history_scan["current_action"],
            "last_history_scan_retry_count": self.last_history_scan["retry_count"],
            "last_history_scan_retry_budget_remaining": self.last_history_scan[
                "retry_budget_remaining"
            ],
            "last_history_scan_retry_pending": self.last_history_scan["retry_pending"],
            "processed_versions": len(self.processed_versions),
            "processing_versions": len(self.processing_versions),
            "sent_captcha_versions": len(self.sent_captcha_versions),
            "captcha_result_text_preemptions": self.captcha_result_text_preemptions,
            "response_messages_sent": self.response_message_count,
            "clicked_versions": len(self.clicked_versions),
            "skipped_finished": self.message_skip_counts["finished"],
            "skipped_non_inbound": self.message_skip_counts["non_inbound"],
            "skipped_duplicate": self.message_skip_counts["duplicate"],
            "skipped_concurrent_duplicate": self.message_skip_counts["concurrent_duplicate"],
            "skipped_clicked_duplicate": self.message_skip_counts["clicked_duplicate"],
            "message_processing_cancelled": self.message_skip_counts["cancelled"],
            "unhandled_messages": self.message_skip_counts["unhandled"],
            "callback_confirmed": self.callback_result_counts["confirmed"],
            "callback_trusted_timeout": self.callback_result_counts["trusted_timeout"],
            "callback_data_invalid_after_timeout": self.callback_result_counts["data_invalid_after_timeout"],
            "callback_unconfirmed": self.callback_result_counts["unconfirmed"],
            "stale_callback_texts": self.stale_callback_texts,
        }

    def _log_timeout_state(self) -> None:
        self.log(
            "事件引擎等待超时状态快照",
            level="WARNING",
            stage="result",
            event="event_engine_timeout_state",
            visible=False,
            meta=self._state_snapshot_meta(),
        )

    def _log_final_state(self, result: EventRunResult, *, source: str) -> None:
        if self._final_state_logged:
            return
        self._final_state_logged = True
        meta = self._state_snapshot_meta()
        meta.update(
            {
                "status": result.status,
                "message": result.message,
                "source": source,
            }
        )
        self.log(
            "事件引擎最终状态快照",
            level="success" if result.status in {EventRunStatus.SUCCESS, EventRunStatus.CHECKED} else "ERROR",
            stage="result",
            event="event_engine_final_state",
            visible=False,
            meta=meta,
        )

    def _normalize_callback_result(self, result) -> CallbackAnswerResult:
        if isinstance(result, CallbackAnswerResult):
            return result
        if isinstance(result, dict):
            status = str(result.get("status") or "").strip()
            confirmed_value = _optional_bool(result.get("confirmed"))
            confirmed = (
                confirmed_value
                if confirmed_value is not None
                else status in {"confirmed", "trusted_timeout", "data_invalid_after_timeout"}
            )
            return CallbackAnswerResult(
                confirmed=confirmed,
                status=status or ("confirmed" if confirmed else "unconfirmed"),
                reason=str(result.get("reason") or ""),
                attempt=_optional_int(result.get("attempt"), minimum=0) or 0,
                max_retries=_optional_int(result.get("max_retries"), minimum=0) or 0,
                timeout=_optional_float(result.get("timeout"), minimum=0.0) or 0.0,
                error_type=str(result.get("error_type") or ""),
                had_timeout=_optional_bool(result.get("had_timeout")) or False,
                callback_text=str(result.get("callback_text") or ""),
                trusted_consumed=_optional_bool(result.get("trusted_consumed")) or False,
            )
        return CallbackAnswerResult(
            confirmed=bool(result),
            status="confirmed" if result else "unconfirmed",
        )

    def _record_callback_result(
        self,
        result: CallbackAnswerResult,
        *,
        message: Message,
        button_text: str,
        source: str,
    ) -> None:
        context = self._callback_context_meta()
        if result.status in self.callback_result_counts:
            self.callback_result_counts[result.status] += 1
        elif result.confirmed:
            self.callback_result_counts["confirmed"] += 1
        else:
            self.callback_result_counts["unconfirmed"] += 1
        self.log(
            "事件引擎按钮回调结果",
            stage="action",
            event="event_engine_button_callback_result",
            visible=False,
            meta={
                "chat_id": message.chat.id,
                "message_id": message.id,
                "button_text": button_text,
                "source": source,
                "attempt_epoch": context["attempt_epoch"],
                "current_response_index": context["current_response_index"],
                "current_action": context["current_action"],
                "retry_count": context["retry_count"],
                "retry_budget_remaining": context["retry_budget_remaining"],
                "retry_pending": context["retry_pending"],
                "confirmed": result.confirmed,
                "callback_status": result.status,
                "callback_reason": result.reason,
                "callback_attempt": result.attempt,
                "callback_max_retries": result.max_retries,
                "callback_timeout": result.timeout,
                "callback_error_type": result.error_type,
                "callback_had_timeout": result.had_timeout,
                "trusted_consumed": result.trusted_consumed,
                "has_callback_text": bool(result.callback_text),
            },
        )

    def _record_button_click_duplicate(self, message: Message, *, button_text: str, source: str) -> None:
        self.message_skip_counts["clicked_duplicate"] += 1
        self.log(
            "事件引擎跳过已点击按钮版本",
            stage="action",
            event="event_engine_button_click_duplicate_skipped",
            visible=False,
            meta={
                "chat_id": self.chat.chat_id,
                "message_id": getattr(message, "id", None),
                "button_text": button_text,
                "source": source,
                "clicked_duplicate": self.message_skip_counts["clicked_duplicate"],
            },
        )

    def _record_message_processing_cancelled(
        self,
        message: Message,
        *,
        version,
        attempt_epoch: int,
    ) -> None:
        self.message_skip_counts["cancelled"] += 1
        action = self._current_response_action()
        self.log(
            "事件引擎消息处理中断，已释放处理中版本",
            level="WARNING",
            stage="message",
            event=EVENT_ENGINE_MESSAGE_PROCESSING_CANCELLED,
            meta={
                "chat_id": getattr(getattr(message, "chat", None), "id", self.chat.chat_id),
                "message_id": getattr(message, "id", None),
                "message_version_hash": self._message_version_hash(version),
                "message_attempt_epoch": attempt_epoch,
                "attempt_epoch": self.attempt_epoch,
                "current_response_index": self.current_response_index,
                "current_action": str(action) if action is not None else "",
                "retry_count": self.retry_count,
                "retry_budget_remaining": self._retry_budget_remaining(),
                "retry_pending": bool(self._retry_task and not self._retry_task.done()),
                "processing_versions": len(self.processing_versions),
                "will_release_processing_version": True,
                "message_processing_cancelled": self.message_skip_counts["cancelled"],
                "finished": self.finished.is_set(),
            },
        )

    def _record_message_skip(self, reason: str, message: Message, *, version=None) -> None:
        version = version or message_version(message)
        log_key = (reason, version)
        if log_key in self.logged_skip_versions:
            return
        self.logged_skip_versions.add(log_key)
        if reason in self.message_skip_counts:
            self.message_skip_counts[reason] += 1
        chat = getattr(message, "chat", None)
        from_user = getattr(message, "from_user", None)
        self.log(
            "事件引擎跳过已处理/处理中消息版本",
            stage="message",
            event="event_engine_message_skip_recorded",
            visible=False,
            meta={
                "chat_id": getattr(chat, "id", self.chat.chat_id),
                "message_id": getattr(message, "id", None),
                "message_version_hash": self._message_version_hash(version),
                "reason": reason,
                "outgoing": bool(getattr(message, "outgoing", False)),
                "from_self": bool(getattr(from_user, "is_self", False)),
                "attempt_epoch": self.attempt_epoch,
                "current_response_index": self.current_response_index,
                "current_action": str(self._current_response_action() or ""),
                "retry_count": self.retry_count,
                "retry_budget_remaining": self._retry_budget_remaining(),
                "retry_pending": bool(self._retry_task and not self._retry_task.done()),
                "skipped_duplicate": self.message_skip_counts["duplicate"],
                "skipped_concurrent_duplicate": self.message_skip_counts["concurrent_duplicate"],
                "skipped_finished": self.message_skip_counts["finished"],
                "skipped_non_inbound": self.message_skip_counts["non_inbound"],
                "skipped_stale_attempt": self.message_skip_counts["stale_attempt"],
            },
        )

    @staticmethod
    def _message_version_hash(version) -> str:
        return hashlib.sha256(repr(version).encode("utf-8")).hexdigest()[:16]

    def _record_message_unhandled(
        self,
        message: Message,
        *,
        version,
        current_action,
        retry_pending: bool,
    ) -> None:
        if version in self.unhandled_versions:
            return
        self.unhandled_versions.add(version)
        self.message_skip_counts["unhandled"] += 1
        self.log(
            "事件引擎收到消息但未命中当前动作或结果关键字",
            level="INFO",
            stage="message",
            event="event_engine_message_unhandled",
            meta={
                "chat_id": getattr(getattr(message, "chat", None), "id", self.chat.chat_id),
                "message_id": getattr(message, "id", None),
                "message_version_hash": self._message_version_hash(version),
                "current_response_index": self.current_response_index,
                "current_action": str(current_action) if current_action is not None else None,
                "retry_pending": bool(retry_pending),
                "has_text": bool(get_message_text_content(message)),
                "has_photo": bool(getattr(message, "photo", None)),
                "has_reply_markup": bool(getattr(message, "reply_markup", None)),
                "unhandled_messages": self.message_skip_counts["unhandled"],
            },
        )

    async def _handle_current_response_action(self, message: Message) -> bool:
        action = self._current_response_action()
        if action is None:
            return False
        if self._handling_startup_history and not self._can_handle_action_from_startup_history(action):
            if self._startup_history_skip_relevant(action, message):
                self.log(
                    "事件引擎跳过启动历史中的旧交互动作",
                    stage="action",
                    event="event_engine_startup_history_action_skipped",
                    meta={
                        "chat_id": self.chat.chat_id,
                        "message_id": getattr(message, "id", None),
                        "action": str(action),
                        "source": "startup_history",
                    },
                )
            return False
        try:
            self._last_response_action_should_advance = True
            handled = await asyncio.wait_for(
                self._execute_response_action(action, message),
                timeout=self.action_timeout,
            )
        except EventHardTimeoutError as e:
            if e.operation in {"send", "media", "ai", "ai_tools", "callback", "history"}:
                raise
            self.log(
                f"事件引擎响应动作超时: {action}",
                level="WARNING",
                stage="action",
                event="event_engine_response_action_timeout",
                meta={
                    "chat_id": self.chat.chat_id,
                    "message_id": getattr(message, "id", None),
                    "action": str(action),
                    "timeout": self.action_timeout,
                },
            )
            raise e
        except asyncio.TimeoutError as e:
            self.log(
                f"事件引擎响应动作超时: {action}",
                level="WARNING",
                stage="action",
                event="event_engine_response_action_timeout",
                meta={
                    "chat_id": self.chat.chat_id,
                    "message_id": getattr(message, "id", None),
                    "action": str(action),
                    "timeout": self.action_timeout,
                },
            )
            raise e
        if handled:
            source = "startup_history" if self._handling_startup_history else "realtime"
            retry_pending = bool(self._retry_task and not self._retry_task.done())
            should_advance = self._last_response_action_should_advance
            if not self.finished.is_set() and not retry_pending and should_advance:
                self._advance_response_action(
                    action=action,
                    message=message,
                    source=source,
                    reason="message_action_handled",
                )
                await self._drain_immediate_response_actions()
                self._finish_if_no_result_required()
            else:
                self._log_response_action_not_advanced(
                    action=action,
                    message=message,
                    source=source,
                    reason=(
                        "finished"
                        if self.finished.is_set()
                        else "retry_pending"
                        if retry_pending
                        else "poetry_fill_pending"
                    ),
                )
        return handled

    async def _execute_response_action(self, action, message: Message) -> bool:
        if isinstance(action, ClickKeyboardByTextAction):
            return await self._click_button(message, action.text, trusted_timeout=not self._handling_startup_history)
        if isinstance(action, ChooseOptionByImageAction):
            return await self._choose_option_by_image(message)
        if isinstance(action, ReplyByCalculationProblemAction):
            return await self._reply_calculation(message)
        if isinstance(action, ReplyByImageRecognitionAction):
            return await self._reply_image_captcha(message)
        if isinstance(action, ClickButtonByCalculationProblemAction):
            return await self._click_calculation_answer(message)
        if isinstance(action, ClickButtonByPoetryFillAction):
            return await self._click_poetry_answer(message)
        return False

    async def _handle_unexpected_interaction(self, message: Message) -> bool:
        if not self.ai_fallback_enabled or not self.spec.requires_result:
            return False
        if self._current_response_action() is not None:
            return False
        if self._retry_task and not self._retry_task.done():
            return False
        text = get_message_text_content(message)
        buttons = _extract_button_texts(message)
        if not text and not buttons:
            return False
        tools = await self._get_ai_tools_with_timeout(message, source="ai_fallback")
        infer = getattr(tools, "infer_sign_interaction", None)
        if infer is None:
            return False
        self.log(
            "事件引擎尝试 AI 处理未配置的后续交互",
            stage="action",
            event="event_engine_ai_fallback_started",
            meta={"chat_id": message.chat.id, "message_id": message.id, "buttons": buttons},
        )
        decision = await self._call_ai_tool(
            message,
            "ai_fallback",
            infer(text, buttons),
        )
        action = str((decision or {}).get("action") or "noop").lower()
        value = str((decision or {}).get("value") or "").strip()
        if action == "click" and value:
            self.log(
                f"事件引擎 AI 决定点击按钮: {value}",
                stage="action",
                event="event_engine_ai_fallback_click",
                meta={"chat_id": message.chat.id, "message_id": message.id, "button_text": value},
            )
            return await self._click_button(message, value, trusted_timeout=True)
        if action == "send" and value:
            self.log(
                f"事件引擎 AI 决定发送文本: {value}",
                stage="action",
                event="event_engine_ai_fallback_send",
                meta={"chat_id": message.chat.id, "message_id": message.id},
            )
            await self._send_response_message(
                message,
                value,
                source="ai_fallback",
            )
            return True
        if action == "status":
            self.log(
                "事件引擎 AI 判断该消息为状态消息，继续等待明确结果",
                stage="result",
                event="event_engine_ai_fallback_status",
                meta={"chat_id": message.chat.id, "message_id": message.id},
            )
            return True
        self.log(
            "事件引擎 AI 判断无需处理该消息",
            stage="action",
            event="event_engine_ai_fallback_noop",
            meta={"chat_id": message.chat.id, "message_id": message.id},
        )
        return False

    async def _walk_history(self, *, rescue: bool = False) -> bool:
        if self.history_limit <= 0:
            return False
        source = "rescue" if rescue else "startup"
        if self.history_scan_lock.locked():
            self.history_scan_counts["concurrent_skipped"] += 1
            self.last_history_scan.update(
                {
                    "source": source,
                    "status": "concurrent_skipped",
                    "message_count": 0,
                    "allowed_count": 0,
                    "handled_count": 0,
                    "error_type": None,
                    **self._hard_timeout_context_meta(),
                }
            )
            self.log(
                "事件引擎已有历史扫描运行中，跳过并发扫描",
                stage="message",
                event="event_engine_history_scan_concurrent_skipped",
                visible=False,
                meta={
                    "chat_id": self.chat.chat_id,
                    "source": source,
                    "status": "concurrent_skipped",
                    "scan_in_progress": True,
                    "concurrent_skipped": self.history_scan_counts["concurrent_skipped"],
                    **self._hard_timeout_context_meta(),
                },
            )
            return False
        async with self.history_scan_lock:
            cancelled_before = self.history_scan_counts["cancelled"]
            try:
                return await self._walk_history_locked(rescue=rescue, source=source)
            except asyncio.CancelledError:
                if self.history_scan_counts["cancelled"] == cancelled_before:
                    self._record_history_scan_cancelled(
                        source=source,
                        message_count=0,
                        allowed_message_ids=set(),
                        handled_message_ids=set(),
                    )
                raise

    async def _walk_history_locked(self, *, rescue: bool, source: str) -> bool:
        if rescue and self.history_rescue_suspended:
            self.log(
                "事件引擎历史补漏已暂停，跳过本次扫描",
                stage="message",
                event="event_engine_history_rescue_suspended",
                visible=False,
                meta={
                    "chat_id": self.chat.chat_id,
                    "source": source,
                    "status": "suspended",
                    "failure_threshold": self.history_failure_threshold,
                    "consecutive_failures": self.history_consecutive_failures,
                    **self._hard_timeout_context_meta(),
                },
            )
            return False
        self.history_scan_counts[source] += 1
        scan_message_count = 0
        allowed_message_ids: set[int] = set()
        handled_message_ids: set[int] = set()
        if rescue:
            self.log(
                "事件引擎扫描最近历史消息进行补漏",
                stage="message",
                event="event_engine_history_rescue_started",
                visible=False,
                meta={"chat_id": self.chat.chat_id, "limit": self.history_limit},
            )
        async def collect_history_messages():
            collected = []
            async for message in self.app.get_chat_history(self.chat.chat_id, limit=self.history_limit):
                collected.append(message)
            return collected

        try:
            messages = await self._await_with_hard_timeout(
                collect_history_messages(),
                timeout=self.history_rpc_timeout,
                operation="history",
                meta={"chat_id": self.chat.chat_id, "source": source},
            )
        except asyncio.CancelledError:
            self._record_history_scan_cancelled(
                source=source,
                message_count=scan_message_count,
                allowed_message_ids=allowed_message_ids,
                handled_message_ids=handled_message_ids,
            )
            raise
        except Exception as e:
            self.history_scan_counts["failed"] += 1
            self.history_consecutive_failures += 1
            will_open_circuit = (
                rescue
                and self.history_failure_threshold > 0
                and self.history_consecutive_failures >= self.history_failure_threshold
            )
            self.last_history_scan.update(
                {
                    "source": source,
                    "status": "failed",
                    "message_count": scan_message_count,
                    "allowed_count": len(allowed_message_ids),
                    "handled_count": len(handled_message_ids),
                    "error_type": _retryable_error_type(e),
                    **self._hard_timeout_context_meta(),
                }
            )
            self.log(
                f"事件引擎读取历史消息失败，跳过历史救援: {e}",
                level="WARNING",
                stage="message",
                event="event_engine_history_failed",
                meta={
                    "chat_id": self.chat.chat_id,
                    "error_type": _retryable_error_type(e),
                    "source": source,
                    "operation": "history",
                    "timeout_scope": "history",
                    "timeout": self.history_rpc_timeout,
                    "operation_timeout": self.history_rpc_timeout,
                    "failed_scans": self.history_scan_counts["failed"],
                    "consecutive_failures": self.history_consecutive_failures,
                    "failure_threshold": self.history_failure_threshold,
                    "rescue": rescue,
                    "will_open_circuit": will_open_circuit,
                    "rescue_suspended": self.history_rescue_suspended or will_open_circuit,
                    "rescue_will_continue": rescue and not will_open_circuit,
                    "scan_in_progress": self.history_scan_lock.locked(),
                    "blocks_main_flow": False,
                    "retry_pending": bool(self._retry_task and not self._retry_task.done()),
                    **self._hard_timeout_context_meta(),
                },
            )
            if will_open_circuit:
                self.history_rescue_suspended = True
                self.history_scan_counts["circuit_opened"] += 1
                self.log(
                    "事件引擎历史补漏连续失败，暂停本轮补漏",
                    level="WARNING",
                    stage="message",
                    event="event_engine_history_rescue_suspended",
                    meta={
                        "chat_id": self.chat.chat_id,
                        "source": source,
                        "status": "suspended",
                        "error_type": _retryable_error_type(e),
                        "timeout": self.history_rpc_timeout,
                        "consecutive_failures": self.history_consecutive_failures,
                        "failure_threshold": self.history_failure_threshold,
                        **self._hard_timeout_context_meta(),
                    },
                )
            return False
        scan_message_count = len(messages)
        self.history_consecutive_failures = 0
        self.history_rescue_suspended = False
        self.history_scan_counts["messages_seen"] += scan_message_count
        ordered_messages = list(reversed(messages))
        if not rescue:
            ids = [
                int(message.id)
                for message in messages
                if isinstance(getattr(message, "id", None), int)
            ]
            if ids:
                self.history_rescue_min_message_id = max(ids)
        result_scan_messages = messages if not rescue else ordered_messages
        for message in result_scan_messages:
            if self.finished.is_set():
                self._finish_history_scan(
                    source,
                    scan_message_count,
                    allowed_message_ids,
                    handled_message_ids,
                    status="finished",
                )
                return True
            if not self._history_message_allowed(message, rescue=rescue, source=source):
                continue
            message_id = getattr(message, "id", None)
            if isinstance(message_id, int):
                allowed_message_ids.add(message_id)
            if not self._is_inbound_chat_message(message):
                continue
            if rescue and self._is_tracked_history_rescue_message(message):
                self._log_tracked_history_recheck(message)
            if self._classify_text(
                get_message_text_content(message),
                source=source,
                message_id=getattr(message, "id", None),
            ):
                if isinstance(message_id, int):
                    handled_message_ids.add(message_id)
                self._finish_history_scan(source, scan_message_count, allowed_message_ids, handled_message_ids, status="handled")
                return True
        handled = False
        for message in ordered_messages:
            if self.finished.is_set():
                self._finish_history_scan(
                    source,
                    scan_message_count,
                    allowed_message_ids,
                    handled_message_ids,
                    status="finished" if not handled else "handled",
                )
                return True
            if not self._history_message_allowed(message, rescue=rescue, source=source):
                continue
            message_id = getattr(message, "id", None)
            if isinstance(message_id, int):
                allowed_message_ids.add(message_id)
            if rescue and self._is_tracked_history_rescue_message(message):
                self._log_tracked_history_recheck(message)
            version = message_version(message)
            if version in self.processed_versions:
                self._log_history_duplicate_skipped(message, source=source, version=version)
                continue
            unhandled_key = self._history_unhandled_key(
                source=source,
                version=version,
                retry_pending=bool(self._retry_task and not self._retry_task.done()),
            )
            if unhandled_key in self.history_unhandled_versions:
                self._log_history_unhandled_duplicate_skipped(
                    message,
                    source=source,
                    version=version,
                    unhandled_key=unhandled_key,
                )
                continue
            before_index = self.current_response_index
            before_finished = self.finished.is_set()
            before_unhandled = self.message_skip_counts["unhandled"]
            previous_startup_history = self._handling_startup_history
            self._handling_startup_history = not rescue
            try:
                await self.handle_message(message)
            finally:
                self._handling_startup_history = previous_startup_history
            if self.finished.is_set() or self.current_response_index != before_index or before_finished:
                handled = True
                if isinstance(message_id, int):
                    handled_message_ids.add(message_id)
                if not rescue:
                    self._track_history_rescue_message(message)
            elif (
                self.message_skip_counts["unhandled"] > before_unhandled
                and version in self.unhandled_versions
            ):
                self.history_unhandled_versions.add(unhandled_key)
        self._finish_history_scan(
            source,
            scan_message_count,
            allowed_message_ids,
            handled_message_ids,
            status="handled" if handled else "idle",
        )
        return handled

    def _record_history_scan_cancelled(
        self,
        *,
        source: str,
        message_count: int,
        allowed_message_ids: set[int],
        handled_message_ids: set[int],
    ) -> None:
        self.history_scan_counts["cancelled"] += 1
        allowed_count = len(allowed_message_ids)
        handled_count = len(handled_message_ids)
        self.last_history_scan.update(
            {
                "source": source,
                "status": "cancelled",
                "message_count": message_count,
                "allowed_count": allowed_count,
                "handled_count": handled_count,
                "error_type": "CancelledError",
                **self._hard_timeout_context_meta(),
            }
        )
        self.log(
            "事件引擎历史扫描被外层取消，已隔离本次扫描状态",
            level="WARNING",
            stage="message",
            event="event_engine_history_scan_cancelled",
            visible=False,
            meta={
                "chat_id": self.chat.chat_id,
                "source": source,
                "status": "cancelled",
                "message_count": message_count,
                "allowed_count": allowed_count,
                "handled_count": handled_count,
                "error_type": "CancelledError",
                "cancelled_scans": self.history_scan_counts["cancelled"],
                "scan_in_progress": self.history_scan_lock.locked(),
                "blocks_main_flow": False,
                "retry_pending": bool(self._retry_task and not self._retry_task.done()),
                **self._hard_timeout_context_meta(),
            },
        )

    def _finish_history_scan(
        self,
        source: str,
        message_count: int,
        allowed_message_ids: set[int],
        handled_message_ids: set[int],
        *,
        status: str,
    ) -> None:
        allowed_count = len(allowed_message_ids)
        handled_count = len(handled_message_ids)
        self.history_scan_counts["messages_allowed"] += allowed_count
        self.history_scan_counts["messages_handled"] += handled_count
        self.last_history_scan.update(
            {
                "source": source,
                "status": status,
                "message_count": message_count,
                "allowed_count": allowed_count,
                "handled_count": handled_count,
                "error_type": None,
                **self._hard_timeout_context_meta(),
            }
        )
        self.log(
            "事件引擎历史扫描完成",
            stage="message",
            event="event_engine_history_scan_completed",
            visible=status not in {"idle"},
            meta={
                "chat_id": self.chat.chat_id,
                "source": source,
                "status": status,
                "message_count": message_count,
                "allowed_count": allowed_count,
                "handled_count": handled_count,
                **self._hard_timeout_context_meta(),
            },
        )

    def _log_tracked_history_recheck(self, message: Message) -> None:
        self.history_scan_counts["tracked_rechecks"] += 1
        self.log(
            "事件引擎复查已处理消息的编辑版本",
            stage="message",
            event="event_engine_history_tracked_message_rechecked",
            visible=False,
            meta={
                "chat_id": self.chat.chat_id,
                "message_id": getattr(message, "id", None),
            },
        )

    def _log_history_duplicate_skipped(self, message: Message, *, source: str, version) -> None:
        duplicate_key = (source, version)
        if duplicate_key in self.history_duplicate_versions:
            return
        self.history_duplicate_versions.add(duplicate_key)
        self.history_scan_counts["duplicates"] += 1
        self.log(
            "事件引擎历史扫描跳过已处理消息版本",
            stage="message",
            event="event_engine_history_duplicate_skipped",
            visible=False,
            meta={
                "chat_id": self.chat.chat_id,
                "message_id": getattr(message, "id", None),
                "source": source,
                "duplicate_count": self.history_scan_counts["duplicates"],
                "version": str(version),
            },
        )

    def _history_unhandled_key(
        self,
        *,
        source: str,
        version,
        retry_pending: bool,
    ) -> tuple:
        action = self._current_response_action()
        return (
            source,
            version,
            self.current_response_index,
            str(action) if action is not None else None,
            bool(retry_pending),
        )

    def _log_history_unhandled_duplicate_skipped(
        self,
        message: Message,
        *,
        source: str,
        version,
        unhandled_key,
    ) -> None:
        if unhandled_key in self.history_unhandled_duplicate_versions:
            return
        self.history_unhandled_duplicate_versions.add(unhandled_key)
        self.history_scan_counts["unhandled_duplicates"] += 1
        self.log(
            "事件引擎历史扫描跳过未处理消息重复版本",
            stage="message",
            event="event_engine_history_unhandled_duplicate_skipped",
            visible=False,
            meta={
                "chat_id": self.chat.chat_id,
                "message_id": getattr(message, "id", None),
                "source": source,
                "message_version_hash": self._message_version_hash(version),
                "current_response_index": self.current_response_index,
                "unhandled_duplicate_count": self.history_scan_counts["unhandled_duplicates"],
            },
        )

    def _log_history_message_filtered(
        self,
        message: Message,
        *,
        source: str,
        reason: str,
        count_key: str,
        age_seconds: int | None = None,
    ) -> None:
        version = message_version(message)
        filter_key = (source, reason, version)
        if filter_key in self.history_filtered_versions:
            return
        self.history_filtered_versions.add(filter_key)
        self.history_scan_counts[count_key] += 1
        meta = {
            "chat_id": self.chat.chat_id,
            "message_id": getattr(message, "id", None),
            "source": source,
            "reason": reason,
            "filtered_before_entry": self.history_scan_counts["filtered_before_entry"],
            "filtered_expired": self.history_scan_counts["filtered_expired"],
        }
        if age_seconds is not None:
            meta["age_seconds"] = age_seconds
        self.log(
            "事件引擎历史扫描过滤消息",
            stage="message",
            event="event_engine_history_message_filtered",
            visible=False,
            meta=meta,
        )

    def _is_tracked_history_rescue_message(self, message: Message) -> bool:
        message_id = getattr(message, "id", None)
        return (
            isinstance(message_id, int)
            and self.history_rescue_min_message_id is not None
            and message_id <= self.history_rescue_min_message_id
            and message_id in self.history_rescue_tracked_message_ids
        )

    def _history_message_allowed(self, message: Message, *, rescue: bool, source: str) -> bool:
        if rescue and self.history_rescue_min_message_id is not None:
            message_id = getattr(message, "id", None)
            if (
                isinstance(message_id, int)
                and message_id <= self.history_rescue_min_message_id
                and message_id not in self.history_rescue_tracked_message_ids
            ):
                self._log_history_message_filtered(
                    message,
                    source=source,
                    reason="before_entry_untracked",
                    count_key="filtered_before_entry",
                )
                return False
        if not rescue and self.history_result_max_age > 0:
            timestamp = getattr(message, "edit_date", None) or getattr(message, "date", None)
            if isinstance(timestamp, datetime):
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds()
                if age > self.history_result_max_age:
                    self.history_scan_counts["expired"] += 1
                    self.log(
                        "事件引擎跳过过期历史消息",
                        stage="message",
                        event="event_engine_history_message_expired",
                        visible=False,
                        meta={
                            "chat_id": self.chat.chat_id,
                            "message_id": getattr(message, "id", None),
                            "age_seconds": int(age),
                        },
                    )
                    self._log_history_message_filtered(
                        message,
                        source=source,
                        reason="expired",
                        count_key="filtered_expired",
                        age_seconds=int(age),
                    )
                    return False
        return True

    def _is_inbound_chat_message(self, message: Message) -> bool:
        if getattr(message, "outgoing", False):
            return False
        from_user = getattr(message, "from_user", None)
        if getattr(from_user, "is_self", False):
            return False
        chat = getattr(message, "chat", None)
        return bool(chat is not None and getattr(chat, "id", None) == self.chat.chat_id)
