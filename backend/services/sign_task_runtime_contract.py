from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Sequence

from tg_signer.event_contract import (
    EVENT_ENGINE_CAPTCHA_RESULT_TEXT_PREEMPTED,
    EVENT_ENGINE_MESSAGE_PROCESSING_CANCELLED,
    EVENT_ENGINE_BUTTON_CALLBACK_RELEASED_FOR_RETRY,
    EVENT_ENGINE_HARD_TIMEOUT_LATE_CANCELLED,
    EVENT_ENGINE_HARD_TIMEOUT_LATE_COMPLETED,
    EVENT_ENGINE_HARD_TIMEOUT_LATE_EXCEPTION,
    EVENT_ENGINE_HARD_TIMEOUT_LATE_EVENTS,
)

EVENT_TASK_RUNTIME_CONFIG = "task_runtime_config"
EVENT_ENGINE_STARTED = "event_engine_started"
EVENT_ENGINE_BUTTON_CLICKED = "event_engine_button_clicked"
EVENT_ENGINE_BUTTON_CALLBACK_RESULT = "event_engine_button_callback_result"
EVENT_ENGINE_HISTORY_SCAN_COMPLETED = "event_engine_history_scan_completed"
EVENT_ENGINE_HISTORY_FAILED = "event_engine_history_failed"
EVENT_ENGINE_HISTORY_SCAN_CANCELLED = "event_engine_history_scan_cancelled"
EVENT_ENGINE_TIMEOUT_STATE = "event_engine_timeout_state"
EVENT_ENGINE_FINAL_STATE = "event_engine_final_state"
EVENT_WORKER_EXECUTION_CONTRACT = "worker_execution_contract"

EVENT_RUN_SUMMARY_STATE_FIELDS = (
    "current_response_index",
    "response_action_count",
    "current_action",
    "attempt_epoch",
)

EVENT_FINAL_STATE_OBSERVABILITY_FIELDS = (
    "source",
    "timeout",
    *EVENT_RUN_SUMMARY_STATE_FIELDS,
    "retry_count",
    "retry_budget_remaining",
    "retry_pending",
    "attempt_epoch",
    "processed_versions",
    "processing_versions",
    "sent_captcha_versions",
    "clicked_versions",
    "skipped_duplicate",
    "skipped_concurrent_duplicate",
    "skipped_clicked_duplicate",
    "skipped_finished",
    "skipped_non_inbound",
    "message_processing_cancelled",
    "unhandled_messages",
    "callback_confirmed",
    "callback_trusted_timeout",
    "callback_data_invalid_after_timeout",
    "callback_unconfirmed",
    "stale_callback_texts",
    "history_startup_scans",
    "history_rescue_scans",
    "history_failed_scans",
    "history_scan_in_progress",
    "history_rescue_suspended",
    "history_consecutive_failures",
    "history_circuit_opened",
    "history_messages_seen",
    "history_messages_allowed",
    "history_messages_handled",
    "history_duplicate_messages",
    "history_unhandled_duplicates",
)
EVENT_FINAL_STATE_CURRENT_MARKERS = ("source", "timeout", "attempt_epoch")
EVENT_BUTTON_CALLBACK_RESULT_OBSERVABILITY_FIELDS = (
    "confirmed",
    "callback_status",
    "callback_attempt",
    "callback_max_retries",
    "callback_timeout",
    "callback_had_timeout",
)
EVENT_BUTTON_CALLBACK_RESULT_RECOMMENDED_FIELDS = (
    "button_text",
    "source",
    "attempt_epoch",
    "current_response_index",
    "current_action",
    "retry_count",
    "retry_pending",
    "retry_budget_remaining",
    "callback_reason",
    "callback_error_type",
    "trusted_consumed",
    "has_callback_text",
)
EVENT_BUTTON_CALLBACK_RELEASED_OBSERVABILITY_FIELDS = (
    "button_text",
    "source",
    "attempt_epoch",
    "current_response_index",
    "current_action",
    "retry_count",
    "retry_pending",
    "retry_budget_remaining",
    "callback_status",
    "callback_attempt",
    "callback_max_retries",
    "callback_timeout",
    "callback_had_timeout",
    "clicked_versions",
    "released_for_retry",
)
EVENT_BUTTON_CALLBACK_UNCONFIRMED_OBSERVABILITY_FIELDS = (
    "button_text",
    "source",
    "attempt_epoch",
    "current_response_index",
    "current_action",
    "retry_count",
    "retry_pending",
    "retry_budget_remaining",
    "callback_status",
    "callback_reason",
    "callback_attempt",
    "callback_max_retries",
    "callback_timeout",
    "callback_error_type",
    "callback_had_timeout",
)
EVENT_HISTORY_SCAN_COMPLETED_OBSERVABILITY_FIELDS = (
    "source",
    "status",
    "message_count",
    "allowed_count",
    "handled_count",
)
EVENT_HISTORY_SCAN_CANCELLED_OBSERVABILITY_FIELDS = (
    "source",
    "status",
    "message_count",
    "allowed_count",
    "handled_count",
    "error_type",
    "cancelled_scans",
    "scan_in_progress",
    "blocks_main_flow",
    "retry_pending",
)
EVENT_HISTORY_FAILED_OBSERVABILITY_FIELDS = (
    "source",
    "operation",
    "timeout_scope",
    "error_type",
    "timeout",
    "operation_timeout",
    "failed_scans",
    "consecutive_failures",
    "failure_threshold",
    "rescue",
    "will_open_circuit",
    "rescue_suspended",
    "rescue_will_continue",
    "scan_in_progress",
    "blocks_main_flow",
    "retry_pending",
)
EVENT_RESULT_MATCH_OBSERVABILITY_FIELDS = (
    "chat_id",
    "source",
    "message_id",
    "attempt_epoch",
    "current_response_index",
    "current_action",
    "retry_count",
    "retry_budget_remaining",
    "retry_pending",
    "keyword",
)
EVENT_RESULT_MATCH_SUMMARY_FIELDS = (
    "event",
    "matched",
    "status",
    "source",
    "message_id",
    "keyword",
    "attempt_epoch",
    "current_response_index",
    "current_action",
    "retry_count",
    "retry_budget_remaining",
    "retry_pending",
)
EVENT_RETRY_EVENT_OBSERVABILITY_FIELDS = (
    "reason",
    "retry_count",
    "max_inline_retries",
    "retry_budget_remaining",
)
EVENT_RETRY_EVENT_RECOMMENDED_FIELDS = (
    "attempt_epoch",
    "current_response_index",
    "current_action",
    "retry_pending",
    "retry_source",
    "retry_message_id",
    "retry_trigger",
)
EVENT_RETRY_EVENT_EXTRA_FIELDS = {
    "event_engine_retry_suppressed": ("suppressed_count",),
    "event_engine_retry_completed": ("finished",),
    "event_engine_retry_cancelled": ("finished",),
    "event_engine_retry_initial_send_error": ("error_type",),
}
EVENT_HARD_TIMEOUT_LATE_OBSERVABILITY_FIELDS = (
    "operation",
    "timeout_scope",
    "timeout",
)
EVENT_HARD_TIMEOUT_LATE_EXTRA_FIELDS = {
    EVENT_ENGINE_HARD_TIMEOUT_LATE_EXCEPTION: ("error_type",),
}
EVENT_HARD_TIMEOUT_LATE_RECOMMENDED_FIELDS = (
    "source",
    "message_id",
    "attempt_epoch",
    "current_response_index",
    "current_action",
    "retry_count",
    "retry_budget_remaining",
    "retry_pending",
)
EVENT_HARD_TIMEOUT_LATE_CANCEL_RECOMMENDED_FIELDS = (
    "cancelled_by_parent",
)
EVENT_MESSAGE_SKIP_OBSERVABILITY_FIELDS = (
    "reason",
    "message_version_hash",
    "attempt_epoch",
    "current_response_index",
    "current_action",
    "retry_count",
    "retry_budget_remaining",
    "retry_pending",
    "skipped_duplicate",
    "skipped_concurrent_duplicate",
    "skipped_finished",
    "skipped_non_inbound",
)
EVENT_MESSAGE_UNHANDLED_OBSERVABILITY_FIELDS = (
    "message_version_hash",
    "current_response_index",
    "current_action",
    "retry_pending",
    "has_text",
    "has_photo",
    "has_reply_markup",
    "unhandled_messages",
)
EVENT_MESSAGE_PROCESSING_CANCELLED_OBSERVABILITY_FIELDS = (
    "message_version_hash",
    "message_attempt_epoch",
    "attempt_epoch",
    "current_response_index",
    "current_action",
    "retry_count",
    "retry_budget_remaining",
    "retry_pending",
    "processing_versions",
    "will_release_processing_version",
    "message_processing_cancelled",
    "finished",
)
EVENT_MESSAGE_RETRYABLE_ERROR_OBSERVABILITY_FIELDS = (
    "message_id",
    "error_type",
    "operation",
    "timeout_scope",
    "operation_timeout",
    "attempt_epoch",
    "current_response_index",
    "current_action",
    "retry_count",
    "retry_budget_remaining",
    "retry_pending",
)
EVENT_RESPONSE_ACTION_ADVANCED_OBSERVABILITY_FIELDS = (
    "from_index",
    "to_index",
    "response_action_count",
    "source",
    "reason",
    "attempt_epoch",
    "retry_count",
    "retry_budget_remaining",
)
EVENT_RESPONSE_ACTION_ADVANCED_RECOMMENDED_FIELDS = (
    "action",
    "next_action",
    "message_id",
)
EVENT_RESPONSE_ACTION_NOT_ADVANCED_OBSERVABILITY_FIELDS = (
    "current_response_index",
    "response_action_count",
    "source",
    "reason",
    "finished",
    "retry_pending",
    "attempt_epoch",
    "retry_count",
    "retry_budget_remaining",
)
EVENT_RESPONSE_ACTION_NOT_ADVANCED_RECOMMENDED_FIELDS = (
    "action",
    "next_action",
    "message_id",
)
EVENT_WORKER_LOCK_WAIT_STARTED_FIELDS = (
    "operation",
    "timeout_scope",
    "locked",
    "timeout_seconds",
)
EVENT_WORKER_LOCK_ACQUIRED_FIELDS = (
    "operation",
    "timeout_scope",
    "wait_seconds",
    "timeout_seconds",
)
EVENT_WORKER_LOCK_WAIT_TIMEOUT_FIELDS = (
    "operation",
    "timeout_scope",
    "wait_seconds",
    "timeout_seconds",
)
EVENT_WORKER_LOCK_RELEASED_FIELDS = (
    "operation",
    "timeout_scope",
    "success",
    "attempt",
    "total_attempts",
)
EVENT_CLIENT_CLEANUP_BASE_FIELDS = (
    "operation",
    "timeout_scope",
    "attempt",
    "total_attempts",
    "success",
    "timeout_seconds",
)
EVENT_CLIENT_CLEANUP_COMPLETED_RECOMMENDED_FIELDS = (
    "lock_present",
    "lock_acquired",
    "lock_wait_timeout",
    "lock_timeout_seconds",
    "force_cleanup",
    "client_found",
    "cleanup_attempted",
    "cleanup_error_type",
    "cleanup_step_attempts",
    "cleanup_step_timeouts",
    "cleanup_step_errors",
    "cleanup_step_last_error_type",
    "cleanup_step_last_timeout",
)
EVENT_CLIENT_CLEANUP_FAILED_EXTRA_FIELDS = (
    "error_type",
)
EVENT_CLIENT_CLEANUP_LATE_EXTRA_FIELDS = {
    "client_cleanup_late_exception": ("error_type",),
}
EVENT_CLIENT_STARTUP_RETRY_FIELDS = (
    "source",
    "operation",
    "attempt",
    "total_attempts",
    "retry_budget_remaining",
    "wait_seconds",
    "cleanup_attempted",
    "error_type",
    "reason",
)

EVENT_ENGINE_NAME = "event"
RUNTIME_CONTRACT_VERSION = 1

SUPPORT_ACTION_IDS = (1, 2, 3, 4, 5, 6, 7, 8, 9)
SUPPORT_ACTION_REQUIRED_FIELDS = {
    1: ("text",),
    2: ("dice",),
    3: ("text",),
    9: ("keywords",),
}
SUPPORT_ACTION_OPTIONAL_KEYWORD_FIELDS = ()
SUPPORT_ACTION_DEPRECATED_ASSERT_KEYWORD_FIELDS = (
    "checked_keywords",
    "retry_keywords",
    "fail_keywords",
    "account_fail_keywords",
    "ignore_keywords",
)
SUPPORT_ACTION_CAPTCHA_CASE_VALUES = ("preserve", "upper", "lower")
SUPPORT_ACTION_REPLY_IMAGE_FIELDS = (
    "caption_pattern",
    "captcha_lengths",
    "captcha_charset",
    "captcha_case",
    "reply_to_message",
)
SUPPORT_ACTION_REPLY_IMAGE_ID = 6
SUPPORT_ACTION_ASSERT_SUCCESS_ID = 9

RUNTIME_REQUIRED_FIELDS = ("engine", "chat_count")
RUNTIME_RECOMMENDED_FIELDS = (
    "runtime_contract_version",
    "runtime_config_key",
    "event_chat_count",
    "configured_action_count",
)
WORKER_REQUIRED_FIELDS = (
    "engine",
    "requires_updates",
    "retry_count",
    "total_attempts",
    "session_retry_count",
)
WORKER_RECOMMENDED_FIELDS = (
    "runtime_contract_version",
    "runtime_config_key",
    "task_timeout_seconds",
    "chat_count",
    "configured_action_count",
)


def normalize_action_text_list(values: Any, *, field_name: str) -> list[str]:
    if isinstance(values, str):
        values = [item.strip() for item in values.split("#")]
    if not isinstance(values, list):
        raise ValueError(f"成功判定动作的 {field_name} 必须为数组")
    normalized: list[str] = []
    seen = set()
    for item in values:
        if not isinstance(item, str):
            raise ValueError(f"成功判定动作的 {field_name} 必须为字符串数组")
        text = item.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _normalize_required_action_text(action: Dict[str, Any], field_name: str) -> None:
    value = action.get(field_name)
    if not isinstance(value, str):
        action_id = action.get("action")
        raise ValueError(f"动作 {action_id} 的 {field_name} 必须为字符串")
    action[field_name] = value.strip()


def _normalize_captcha_lengths(value: Any) -> list[int] | None:
    if value in (None, ""):
        return None
    if not isinstance(value, list):
        raise ValueError("识图回复动作的 captcha_lengths 必须为数组")
    lengths: list[int] = []
    for item in value:
        if isinstance(item, bool):
            raise ValueError("识图回复动作的 captcha_lengths 必须为正整数")
        try:
            length = int(item)
        except (TypeError, ValueError):
            raise ValueError("识图回复动作的 captcha_lengths 必须为正整数")
        if length <= 0:
            raise ValueError("识图回复动作的 captcha_lengths 必须为正整数")
        lengths.append(length)
    return sorted(set(lengths))


def _normalize_reply_image_action_config(action: Dict[str, Any]) -> None:
    caption_pattern = action.get("caption_pattern")
    if caption_pattern is not None:
        if not isinstance(caption_pattern, str):
            raise ValueError("识图回复动作的 caption_pattern 必须为字符串")
        normalized_caption = caption_pattern.strip()
        if normalized_caption:
            action["caption_pattern"] = normalized_caption
        else:
            action.pop("caption_pattern", None)

    normalized_lengths = _normalize_captcha_lengths(action.get("captcha_lengths"))
    if not normalized_lengths:
        action.pop("captcha_lengths", None)
    else:
        action["captcha_lengths"] = normalized_lengths

    captcha_charset = action.get("captcha_charset")
    if captcha_charset is not None:
        if not isinstance(captcha_charset, str):
            raise ValueError("识图回复动作的 captcha_charset 必须为字符串")
        normalized_charset = "".join(dict.fromkeys(captcha_charset.strip()))
        if normalized_charset:
            action["captcha_charset"] = normalized_charset
        else:
            action.pop("captcha_charset", None)

    captcha_case = action.get("captcha_case")
    if captcha_case in (None, ""):
        action.pop("captcha_case", None)
    else:
        normalized_case = str(captcha_case).strip().lower()
        if normalized_case not in SUPPORT_ACTION_CAPTCHA_CASE_VALUES:
            raise ValueError(
                "识图回复动作的 captcha_case 必须为 preserve、upper 或 lower"
            )
        action["captcha_case"] = normalized_case

    if "reply_to_message" in action and not isinstance(action["reply_to_message"], bool):
        raise ValueError("识图回复动作的 reply_to_message 必须为布尔值")


def normalize_sign_action(action: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(action)
    if isinstance(normalized.get("action"), bool):
        raise ValueError("动作类型必须为数字")
    try:
        action_id = int(normalized.get("action", 0) or 0)
    except (TypeError, ValueError):
        raise ValueError("动作类型必须为数字")
    if action_id not in SUPPORT_ACTION_IDS:
        raise ValueError(f"不支持的动作类型: {action_id}")
    normalized["action"] = action_id

    for field_name in SUPPORT_ACTION_REQUIRED_FIELDS.get(action_id, ()):
        value = normalized.get(field_name)
        if isinstance(value, str):
            if not value.strip():
                raise ValueError(f"动作 {action_id} 的 {field_name} 不能为空")
        elif value in (None, []):
            raise ValueError(f"动作 {action_id} 缺少必填字段 {field_name}")
        if field_name != "keywords":
            _normalize_required_action_text(normalized, field_name)

    if action_id == SUPPORT_ACTION_REPLY_IMAGE_ID:
        _normalize_reply_image_action_config(normalized)

    if action_id == SUPPORT_ACTION_ASSERT_SUCCESS_ID:
        for field_name in SUPPORT_ACTION_DEPRECATED_ASSERT_KEYWORD_FIELDS:
            normalized.pop(field_name, None)
        keywords = normalized.get("keywords")
        if not isinstance(keywords, list):
            raise ValueError("成功判定动作的 keywords 必须为数组")
        normalized_keywords = normalize_action_text_list(
            keywords,
            field_name="keywords",
        )
        if not normalized_keywords:
            raise ValueError("成功判定动作至少需要一个关键字")
        normalized["keywords"] = normalized_keywords
        for field_name in SUPPORT_ACTION_OPTIONAL_KEYWORD_FIELDS:
            values = normalized.get(field_name)
            if values is None:
                continue
            normalized_values = normalize_action_text_list(
                values,
                field_name=field_name,
            )
            if normalized_values:
                normalized[field_name] = normalized_values
            else:
                normalized.pop(field_name, None)

    return normalized


def normalize_sign_actions(actions: Sequence[Dict[str, Any]]) -> list[Dict[str, Any]]:
    if not actions:
        raise ValueError("动作列表不能为空")
    normalized_actions: list[Dict[str, Any]] = []
    for action in actions:
        if not isinstance(action, dict):
            raise ValueError("动作必须为对象")
        normalized_actions.append(normalize_sign_action(action))
    return normalized_actions


@dataclass(frozen=True)
class RuntimeNumericBudgetField:
    source: str
    snapshot_key: str
    caster: Callable[[Any], int | float]
    minimum: int | float
    detail_label: str
    state_key: str
    summary_key: str


@dataclass(frozen=True)
class RuntimeBooleanCountField:
    source: str
    enabled_count_key: str
    disabled_count_key: str
    detail_label: str
    summary_enabled_key: str
    summary_disabled_key: str


EVENT_NUMERIC_BUDGET_FIELDS = (
    RuntimeNumericBudgetField("event_timeout", "max_event_timeout", float, 1.0, "event_timeout", "timeout", "event_timeout"),
    RuntimeNumericBudgetField(
        "event_retries",
        "max_event_retries",
        int,
        0,
        "event_retries",
        "max_inline_retries",
        "max_inline_retries",
    ),
    RuntimeNumericBudgetField("event_retry_wait", "max_event_retry_wait", float, 0.0, "retry_wait", "retry_wait", "retry_wait"),
    RuntimeNumericBudgetField("event_history_limit", "max_event_history_limit", int, 0, "history_limit", "history_limit", "history_limit"),
    RuntimeNumericBudgetField(
        "event_history_failure_threshold",
        "max_event_history_failure_threshold",
        int,
        0,
        "history_failure_threshold",
        "history_failure_threshold",
        "history_failure_threshold",
    ),
    RuntimeNumericBudgetField(
        "event_history_rescue_interval",
        "max_event_history_rescue_interval",
        float,
        0.0,
        "history_rescue_interval",
        "history_rescue_interval",
        "history_rescue_interval",
    ),
    RuntimeNumericBudgetField(
        "event_history_rpc_timeout",
        "max_event_history_rpc_timeout",
        float,
        1.0,
        "history_rpc_timeout",
        "history_rpc_timeout",
        "history_rpc_timeout",
    ),
    RuntimeNumericBudgetField(
        "event_history_result_max_age",
        "max_event_history_result_max_age",
        float,
        0.0,
        "history_result_max_age",
        "history_result_max_age",
        "history_result_max_age",
    ),
    RuntimeNumericBudgetField(
        "event_action_timeout",
        "max_event_action_timeout",
        float,
        1.0,
        "action_timeout",
        "action_timeout",
        "action_timeout",
    ),
    RuntimeNumericBudgetField("event_send_timeout", "max_event_send_timeout", float, 1.0, "send_timeout", "send_timeout", "send_timeout"),
    RuntimeNumericBudgetField("event_media_timeout", "max_event_media_timeout", float, 1.0, "media_timeout", "media_timeout", "media_timeout"),
    RuntimeNumericBudgetField("event_ai_timeout", "max_event_ai_timeout", float, 1.0, "ai_timeout", "ai_timeout", "ai_timeout"),
    RuntimeNumericBudgetField(
        "event_callback_timeout",
        "max_event_callback_timeout",
        float,
        0.1,
        "callback_timeout",
        "callback_timeout",
        "callback_timeout",
    ),
    RuntimeNumericBudgetField(
        "event_callback_retries",
        "max_event_callback_retries",
        int,
        1,
        "callback_retries",
        "callback_retries",
        "callback_retries",
    ),
)
EVENT_NUMERIC_BUDGET_MINIMUMS = {
    field.source: field.minimum for field in EVENT_NUMERIC_BUDGET_FIELDS
}
EVENT_NUMERIC_BUDGET_INT_FIELDS = tuple(
    field.source for field in EVENT_NUMERIC_BUDGET_FIELDS if field.caster is int
)
EVENT_BOOLEAN_COUNT_FIELDS = (
    RuntimeBooleanCountField(
        "event_ai_fallback",
        "event_ai_fallback_enabled_count",
        "event_ai_fallback_disabled_count",
        "ai_fallback",
        "ai_fallback_enabled_count",
        "ai_fallback_disabled_count",
    ),
)
EVENT_CHAT_RUNTIME_CONFIG_FIELDS = tuple(
    field.source for field in EVENT_NUMERIC_BUDGET_FIELDS
) + tuple(field.source for field in EVENT_BOOLEAN_COUNT_FIELDS)
EVENT_RUNTIME_SHAPE_SUMMARY_FIELDS = (
    "chat_count",
    "event_chat_count",
    "configured_action_count",
    "send_action_count",
    "button_action_count",
    "image_option_action_count",
    "captcha_action_count",
    "captcha_caption_pattern_count",
    "captcha_length_constrained_count",
    "captcha_charset_constrained_count",
    "captcha_reply_to_message_count",
    "assertion_action_count",
    "requires_result_assertion",
)
EVENT_RUNTIME_SUMMARY_FIELDS = tuple(
    field.summary_key for field in EVENT_NUMERIC_BUDGET_FIELDS
) + tuple(
    key
    for field in EVENT_BOOLEAN_COUNT_FIELDS
    for key in (field.summary_enabled_key, field.summary_disabled_key)
) + (
    "runtime_config_key",
    "ai_fallback_enabled",
    *EVENT_RUNTIME_SHAPE_SUMMARY_FIELDS,
)
EVENT_RETRY_SUMMARY_FIELDS = (
    "last_event",
    "last_reason",
    "last_retry_count",
    "last_budget_remaining",
    "last_attempt_epoch",
    "last_source",
    "last_message_id",
    "last_trigger",
    "attempt_state_resets",
    "last_reset_previous_attempt_epoch",
    "last_reset_attempt_epoch",
    "last_reset_cleared_processed_versions",
    "last_reset_cleared_sent_captcha_versions",
    "last_reset_cleared_clicked_versions",
    "last_reset_cleared_history_duplicates",
    "last_reset_cleared_history_filtered",
    "last_reset_cleared_history_unhandled",
    "last_reset_cleared_history_unhandled_duplicates",
    "last_reset_cleared_history_tracked_message_ids",
    "last_current_response_index",
    "last_current_action",
    "last_retry_pending",
    "scheduled_count",
    "started_count",
    "completed_count",
    "cancelled_count",
    "suppressed_count",
    "initial_send_failed_count",
    "initial_send_error_count",
    "limit_exceeded",
    "limit_exceeded_count",
    "max_inline_retries",
    "task_configured_count",
    "task_configured_total_attempts",
    "task_last_event",
    "task_scheduled_count",
    "task_started_count",
    "task_last_attempt",
    "task_last_total_attempts",
    "task_last_retry_count",
    "task_last_budget_remaining",
    "task_last_error_type",
    "task_last_retryable",
)
EVENT_CALLBACK_SUMMARY_FIELDS = (
    "confirmed",
    "trusted_timeout",
    "data_invalid_after_timeout",
    "unconfirmed",
    "total_results",
    "outer_timeouts",
    "exceptions",
    "released_for_retry",
    "callback_texts",
    "stale_callback_texts",
    "last_status",
    "last_reason",
    "last_source",
    "last_current_response_index",
    "last_current_action",
    "last_retry_pending",
    "last_retry_budget_remaining",
    "last_message_id",
    "last_button_text",
    "last_confirmed",
    "last_attempt",
    "last_max_retries",
    "last_timeout",
    "last_error_type",
    "last_had_timeout",
    "last_trusted_consumed",
    "last_has_callback_text",
    "last_outer_timeout_source",
    "last_outer_timeout_scope",
    "last_outer_operation_timeout",
    "last_outer_timeout_attempt_epoch",
    "last_outer_timeout_current_response_index",
    "last_outer_timeout_current_action",
    "last_outer_timeout_retry_count",
    "last_outer_timeout_retry_budget_remaining",
    "last_outer_timeout_retry_pending",
    "last_exception_source",
    "last_exception_error_type",
    "last_exception_operation_timeout",
    "last_unconfirmed_source",
    "last_unconfirmed_message_id",
    "last_unconfirmed_button_text",
    "last_unconfirmed_status",
    "last_unconfirmed_reason",
    "last_unconfirmed_attempt_epoch",
    "last_unconfirmed_current_response_index",
    "last_unconfirmed_current_action",
    "last_unconfirmed_retry_count",
    "last_unconfirmed_retry_budget_remaining",
    "last_unconfirmed_retry_pending",
    "last_unconfirmed_attempt",
    "last_unconfirmed_max_retries",
    "last_unconfirmed_timeout",
    "last_unconfirmed_error_type",
    "last_unconfirmed_had_timeout",
    "last_released_source",
    "last_released_message_id",
    "last_released_button_text",
    "last_released_status",
    "last_released_attempt_epoch",
    "last_released_current_response_index",
    "last_released_current_action",
    "last_released_retry_count",
    "last_released_retry_budget_remaining",
    "last_released_attempt",
    "last_released_max_retries",
    "last_released_timeout",
    "last_released_retry_pending",
    "last_released_clicked_versions",
    "last_stale_callback_text_message_id",
    "last_stale_callback_text_attempt_epoch",
    "last_stale_callback_text_current_epoch",
)
EVENT_TIMEOUT_SUMMARY_FIELDS = (
    "timeout_count_total",
    "event",
    "response_action",
    "callback_outer",
    "send_rpc",
    "media_rpc",
    "ai_rpc",
    "task_run",
    "client_rpc",
    "client_cleanup_rpc",
    "client_cleanup_rpc_last_timeout",
    "client_rpc_late_cancelled",
    "client_rpc_late_completed",
    "client_rpc_late_exception",
    "client_rpc_last_late_event",
    "client_rpc_last_late_operation",
    "client_rpc_last_late_timeout_scope",
    "client_rpc_last_late_error_type",
    "client_rpc_last_late_timeout",
    "client_startup_retry",
    "client_startup_retry_last_attempt",
    "client_startup_retry_total_attempts",
    "client_startup_retry_budget_remaining",
    "client_startup_retry_wait_seconds",
    "client_startup_retry_cleanup_attempted",
    "client_startup_retry_error_type",
    "client_startup_retry_reason",
    "client_startup_lock",
    "client_startup_lock_timeout_seconds",
    "client_exit_lock",
    "client_exit_lock_timeout_seconds",
    "client_close_lock",
    "client_close_lock_timeout_seconds",
    "task_run_late_cancelled",
    "task_run_late_completed",
    "task_run_late_exception",
    "task_run_last_late_event",
    "task_run_last_late_operation",
    "task_run_last_late_timeout_scope",
    "task_run_last_late_error_type",
    "task_run_last_late_timeout_seconds",
    "task_run_last_late_attempt",
    "task_run_last_late_total_attempts",
    "task_run_cancelled",
    "task_run_cleanup_expected",
    "task_run_operation",
    "task_run_timeout_scope",
    "task_run_timeout_seconds",
    "task_run_attempt",
    "task_run_total_attempts",
    "late_cancelled",
    "late_completed",
    "late_exception",
    "last_late_event",
    "last_late_operation",
    "last_late_timeout_scope",
    "last_late_source",
    "last_late_message_id",
    "last_late_error_type",
    "last_late_timeout",
    "last_late_cancelled_by_parent",
    "last_late_attempt_epoch",
    "last_late_current_response_index",
    "last_late_current_action",
    "last_late_retry_count",
    "last_late_retry_budget_remaining",
    "last_late_retry_pending",
    "last_rpc_event",
    "last_rpc_kind",
    "last_rpc_operation",
    "last_rpc_timeout_scope",
    "last_rpc_source",
    "last_rpc_message_id",
    "last_rpc_source_message_id",
    "last_rpc_error_type",
    "last_rpc_timeout",
)
EVENT_CLEANUP_SUMMARY_FIELDS = (
    "started",
    "completed",
    "failed",
    "last_event",
    "last_attempt",
    "last_total_attempts",
    "last_success",
    "last_operation",
    "last_timeout_scope",
    "error_type",
    "timeout_seconds",
    "manager_lock_present",
    "manager_lock_acquired",
    "manager_lock_wait_timeout",
    "manager_lock_timeout_seconds",
    "manager_force_cleanup",
    "manager_client_found",
    "manager_cleanup_attempted",
    "manager_cleanup_error_type",
    "rpc_attempts",
    "rpc_timeouts",
    "rpc_errors",
    "last_rpc_error_type",
    "last_rpc_timeout",
    "rpc_late_cancelled",
    "rpc_late_completed",
    "rpc_late_exception",
    "last_rpc_late_event",
    "last_rpc_late_error_type",
    "last_rpc_late_timeout",
    "deferred_cancellations",
    "last_deferred_cancel_attempt",
    "last_deferred_cancel_total_attempts",
    "last_deferred_cancel_success",
    "last_deferred_cancel_timeout_seconds",
    "late_cancelled",
    "late_completed",
    "late_exception",
    "last_late_event",
    "last_late_operation",
    "last_late_timeout_scope",
    "last_late_error_type",
    "last_late_timeout_seconds",
    "last_late_attempt",
    "last_late_total_attempts",
    "last_late_success",
)
EVENT_LOCK_SUMMARY_FIELDS = (
    "waited",
    "acquired",
    "wait_timeout",
    "last_operation",
    "last_timeout_scope",
    "wait_timeout_seconds",
    "released",
    "wait_seconds",
    "release_success",
    "release_attempt",
    "release_total_attempts",
)
EVENT_MESSAGE_SUMMARY_FIELDS = (
    "processed_versions",
    "processing_versions",
    "sent_captcha_versions",
    "captcha_result_text_preemptions",
    "response_messages_sent",
    "response_actions_advanced",
    "last_response_action_from_index",
    "last_response_action_to_index",
    "last_response_action_source",
    "last_response_action_reason",
    "last_response_action_attempt_epoch",
    "last_response_action_message_id",
    "response_actions_not_advanced",
    "last_response_action_not_advanced_index",
    "last_response_action_not_advanced_source",
    "last_response_action_not_advanced_reason",
    "last_response_action_not_advanced_finished",
    "last_response_action_not_advanced_retry_pending",
    "last_response_action_not_advanced_attempt_epoch",
    "last_response_action_not_advanced_message_id",
    "message_retryable_errors",
    "last_message_retryable_message_id",
    "last_message_retryable_error_type",
    "last_message_retryable_operation",
    "last_message_retryable_timeout_scope",
    "last_message_retryable_operation_timeout",
    "last_message_retryable_attempt_epoch",
    "last_message_retryable_current_response_index",
    "last_message_retryable_current_action",
    "last_message_retryable_retry_count",
    "last_message_retryable_retry_budget_remaining",
    "last_message_retryable_retry_pending",
    "clicked_versions",
    "skipped_clicked_duplicate",
    "skipped_duplicate",
    "skipped_concurrent_duplicate",
    "skipped_finished",
    "skipped_non_inbound",
    "message_processing_cancelled",
    "stale_attempt_processed_marks",
    "last_stale_attempt_message_epoch",
    "last_stale_attempt_current_epoch",
    "last_skip_reason",
    "last_skip_message_id",
    "last_skip_message_version_hash",
    "last_skip_attempt_epoch",
    "last_skip_current_response_index",
    "last_skip_current_action",
    "last_skip_retry_count",
    "last_skip_retry_budget_remaining",
    "last_skip_retry_pending",
    "unhandled",
)
EVENT_HISTORY_SUMMARY_FIELDS = (
    "startup_scans",
    "rescue_scans",
    "failed_scans",
    "messages_handled",
    "duplicate_messages",
    "messages_seen",
    "messages_allowed",
    "tracked_rechecks",
    "concurrent_skipped",
    "cancelled_scans",
    "scan_in_progress",
    "rescue_suspended",
    "circuit_opened",
    "consecutive_failures",
    "expired_messages",
    "filtered_before_entry",
    "filtered_expired",
    "hard_failures_skipped",
    "unhandled_duplicates",
    "last_scan_status",
    "last_scan_source",
    "last_scan_message_count",
    "last_scan_allowed_count",
    "last_scan_handled_count",
    "last_scan_error_type",
    "last_scan_attempt_epoch",
    "last_scan_current_response_index",
    "last_scan_current_action",
    "last_scan_retry_count",
    "last_scan_retry_budget_remaining",
    "last_scan_retry_pending",
    "last_failed_source",
    "last_failed_operation",
    "last_failed_timeout_scope",
    "last_failed_error_type",
    "last_failed_timeout",
    "last_failed_scan_count",
    "last_failure_scan_in_progress",
    "last_failure_blocks_main_flow",
    "last_failure_retry_pending",
    "last_failure_will_open_circuit",
    "last_failure_rescue_will_continue",
    "last_suspended_source",
    "last_suspended_status",
    "last_suspended_attempt_epoch",
    "last_suspended_current_response_index",
    "last_suspended_current_action",
    "last_suspended_retry_count",
    "last_suspended_retry_budget_remaining",
    "last_suspended_retry_pending",
)

RUNTIME_SHAPE_FIELDS = (
    "chat_count",
    "event_chat_count",
    "configured_action_count",
    "send_action_count",
    "button_action_count",
    "image_option_action_count",
    "captcha_action_count",
    "captcha_caption_pattern_count",
    "captcha_length_constrained_count",
    "captcha_charset_constrained_count",
    "captcha_reply_to_message_count",
    "assertion_action_count",
    "requires_result_assertion",
)
RUNTIME_BOOLEAN_COUNT_SNAPSHOT_FIELDS = tuple(
    key
    for field in EVENT_BOOLEAN_COUNT_FIELDS
    for key in (field.enabled_count_key, field.disabled_count_key)
)
RUNTIME_CONFIG_KEY_FIELDS = (
    "engine",
    *RUNTIME_SHAPE_FIELDS,
    *(field.snapshot_key for field in EVENT_NUMERIC_BUDGET_FIELDS),
    *RUNTIME_BOOLEAN_COUNT_SNAPSHOT_FIELDS,
)
WORKER_RUNTIME_CONSISTENCY_FIELDS = (
    "runtime_contract_version",
    "engine",
    "runtime_config_key",
    *RUNTIME_SHAPE_FIELDS,
    *(field.snapshot_key for field in EVENT_NUMERIC_BUDGET_FIELDS),
    *RUNTIME_BOOLEAN_COUNT_SNAPSHOT_FIELDS,
)
WORKER_RUNTIME_PASSTHROUGH_FIELDS = (
    "runtime_config_key",
    *RUNTIME_SHAPE_FIELDS,
    *(field.snapshot_key for field in EVENT_NUMERIC_BUDGET_FIELDS),
    *RUNTIME_BOOLEAN_COUNT_SNAPSHOT_FIELDS,
)


@dataclass(frozen=True)
class RuntimeSnapshotValidation:
    valid: bool
    engine: str
    missing_required: tuple[str, ...] = ()
    missing_recommended: tuple[str, ...] = ()
    detail_parts: tuple[str, ...] = ()
    current: bool = True


@dataclass(frozen=True)
class WorkerExecutionPlan:
    """Generic worker-side execution input, safe to log and persist.

    This is intentionally free of account names, task names, chat ids, bot names,
    session strings, API credentials, and proxy values.
    """

    requires_updates: bool
    no_updates: bool
    retry_count: int
    total_attempts: int
    task_timeout_seconds: int | float | None
    session_retry_count: int
    runtime_meta: Dict[str, Any]
    worker_meta: Dict[str, Any]


def _as_chats(task_config: Dict[str, Any] | None) -> list[Dict[str, Any]]:
    if not isinstance(task_config, dict):
        return []
    chats = task_config.get("chats")
    if not isinstance(chats, list):
        return []
    return [chat for chat in chats if isinstance(chat, dict)]


def _append_numeric(
    chat: Dict[str, Any],
    source: str,
    target: list[Any],
    caster,
    *,
    minimum: int | float | None = None,
) -> None:
    value = chat.get(source)
    if isinstance(value, bool):
        return
    if value is None:
        return
    try:
        normalized = caster(value)
    except (TypeError, ValueError):
        return
    if minimum is not None:
        normalized = max(normalized, minimum)
    target.append(normalized)


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _optional_nonnegative_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    if isinstance(value, int):
        return max(value, 0)
    try:
        return max(float(value), 0.0)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return None


def _append_runtime_budget_detail_parts(meta: Dict[str, Any], detail_parts: list[str]) -> None:
    for field in EVENT_NUMERIC_BUDGET_FIELDS:
        if meta.get(field.snapshot_key) is not None:
            detail_parts.append(f"{field.detail_label}<={meta.get(field.snapshot_key)}")
    for field in EVENT_BOOLEAN_COUNT_FIELDS:
        enabled = meta.get(field.enabled_count_key, 0)
        disabled = meta.get(field.disabled_count_key, 0)
        if enabled or disabled:
            detail_parts.append(f"{field.detail_label}={enabled}/{disabled}")


def _build_runtime_config_key(snapshot: Dict[str, Any]) -> str:
    parts = [f"contract=v{snapshot.get('runtime_contract_version', RUNTIME_CONTRACT_VERSION)}"]
    for field in RUNTIME_CONFIG_KEY_FIELDS:
        if field in snapshot:
            parts.append(f"{field}={snapshot[field]}")
    return "|".join(parts)


def build_runtime_config_snapshot(task_config: Dict[str, Any] | None) -> Dict[str, Any]:
    """Build the stable backend-facing worker runtime snapshot.

    The snapshot is intentionally generic: it describes execution budget and action
    shape without embedding task names, bot names, chat ids, or per-site behavior.
    """

    chats = _as_chats(task_config)
    snapshot: Dict[str, Any] = {
        "runtime_contract_version": RUNTIME_CONTRACT_VERSION,
        "engine": EVENT_ENGINE_NAME,
        "chat_count": len(chats),
        "event_chat_count": len(chats),
    }

    numeric_budget_values: Dict[str, list[int | float]] = {
        field.snapshot_key: [] for field in EVENT_NUMERIC_BUDGET_FIELDS
    }
    boolean_counts: Dict[str, int] = {}
    for field in EVENT_BOOLEAN_COUNT_FIELDS:
        boolean_counts[field.enabled_count_key] = 0
        boolean_counts[field.disabled_count_key] = 0

    configured_action_count = 0
    send_action_count = 0
    button_action_count = 0
    image_option_action_count = 0
    captcha_action_count = 0
    captcha_caption_pattern_count = 0
    captcha_length_constrained_count = 0
    captcha_charset_constrained_count = 0
    captcha_reply_to_message_count = 0
    assertion_action_count = 0

    for chat in chats:
        for field in EVENT_NUMERIC_BUDGET_FIELDS:
            _append_numeric(
                chat,
                field.source,
                numeric_budget_values[field.snapshot_key],
                field.caster,
                minimum=field.minimum,
            )
        for field in EVENT_BOOLEAN_COUNT_FIELDS:
            value = _optional_bool(chat.get(field.source))
            if value is True:
                boolean_counts[field.enabled_count_key] += 1
            elif value is False:
                boolean_counts[field.disabled_count_key] += 1

        actions = chat.get("actions")
        if not isinstance(actions, list):
            continue
        for action in actions:
            if not isinstance(action, dict):
                continue
            configured_action_count += 1
            try:
                action_type = int(action.get("action", 0) or 0)
            except (TypeError, ValueError):
                action_type = 0
            if action_type in {1, 2}:
                send_action_count += 1
            elif action_type == 3:
                button_action_count += 1
            elif action_type == 4:
                image_option_action_count += 1
            elif action_type == 6:
                captcha_action_count += 1
                caption_pattern = action.get("caption_pattern")
                if isinstance(caption_pattern, str) and caption_pattern.strip():
                    captcha_caption_pattern_count += 1
                captcha_lengths = action.get("captcha_lengths")
                if isinstance(captcha_lengths, list) and captcha_lengths:
                    captcha_length_constrained_count += 1
                captcha_charset = action.get("captcha_charset")
                if isinstance(captcha_charset, str) and captcha_charset.strip():
                    captcha_charset_constrained_count += 1
                if _optional_bool(action.get("reply_to_message")) is True:
                    captcha_reply_to_message_count += 1
            elif action_type == 9:
                assertion_action_count += 1

    snapshot.update(
        {
            "configured_action_count": configured_action_count,
            "send_action_count": send_action_count,
            "button_action_count": button_action_count,
            "image_option_action_count": image_option_action_count,
            "captcha_action_count": captcha_action_count,
            "captcha_caption_pattern_count": captcha_caption_pattern_count,
            "captcha_length_constrained_count": captcha_length_constrained_count,
            "captcha_charset_constrained_count": captcha_charset_constrained_count,
            "captcha_reply_to_message_count": captcha_reply_to_message_count,
            "assertion_action_count": assertion_action_count,
            "requires_result_assertion": assertion_action_count > 0,
            **boolean_counts,
        }
    )
    for snapshot_key, values in numeric_budget_values.items():
        if values:
            snapshot[snapshot_key] = max(values)
    snapshot["runtime_config_key"] = _build_runtime_config_key(snapshot)
    return snapshot


def build_worker_execution_snapshot(
    task_config: Dict[str, Any] | None,
    *,
    requires_updates: bool,
    retry_count: int,
    task_timeout_seconds: int | float | None,
    session_retry_count: int,
) -> Dict[str, Any]:
    """Build a generic worker execution contract snapshot.

    This is the backend/worker boundary view: it describes what the worker will
    actually do with the normalized task config, without including account,
    task, chat, or bot identifiers.
    """

    normalized_retry_count = _nonnegative_int(retry_count)
    normalized_session_retry_count = _nonnegative_int(session_retry_count)
    total_attempts = normalized_retry_count + 1
    snapshot: Dict[str, Any] = {
        "runtime_contract_version": RUNTIME_CONTRACT_VERSION,
        "engine": EVENT_ENGINE_NAME,
        "requires_updates": bool(requires_updates),
        "retry_count": normalized_retry_count,
        "total_attempts": total_attempts,
        "session_retry_count": normalized_session_retry_count,
    }
    normalized_task_timeout_seconds = _optional_nonnegative_number(task_timeout_seconds)
    if normalized_task_timeout_seconds is not None:
        snapshot["task_timeout_seconds"] = normalized_task_timeout_seconds

    config_snapshot = build_runtime_config_snapshot(task_config)
    for field in WORKER_RUNTIME_PASSTHROUGH_FIELDS:
        if field in config_snapshot:
            snapshot[field] = config_snapshot[field]
    return snapshot


def build_worker_execution_plan(
    task_config: Dict[str, Any] | None,
    *,
    requires_updates: bool,
    retry_count: int,
    task_timeout_seconds: int | float | None,
    session_retry_count: int,
) -> WorkerExecutionPlan:
    normalized_retry_count = _nonnegative_int(retry_count)
    normalized_session_retry_count = _nonnegative_int(session_retry_count)
    normalized_task_timeout_seconds = _optional_nonnegative_number(task_timeout_seconds)
    runtime_meta = build_runtime_config_snapshot(task_config)
    worker_meta = build_worker_execution_snapshot(
        task_config,
        requires_updates=requires_updates,
        retry_count=normalized_retry_count,
        task_timeout_seconds=normalized_task_timeout_seconds,
        session_retry_count=normalized_session_retry_count,
    )
    return WorkerExecutionPlan(
        requires_updates=bool(requires_updates),
        no_updates=not bool(requires_updates),
        retry_count=normalized_retry_count,
        total_attempts=normalized_retry_count + 1,
        task_timeout_seconds=normalized_task_timeout_seconds,
        session_retry_count=normalized_session_retry_count,
        runtime_meta=runtime_meta,
        worker_meta=worker_meta,
    )


def validate_runtime_config_snapshot(meta: Dict[str, Any]) -> RuntimeSnapshotValidation:
    if not isinstance(meta, dict):
        meta = {}
    engine = str(meta.get("engine") or "")
    missing_required = tuple(key for key in RUNTIME_REQUIRED_FIELDS if key not in meta)
    missing_recommended = tuple(key for key in RUNTIME_RECOMMENDED_FIELDS if key not in meta)
    valid = not missing_required and engine == EVENT_ENGINE_NAME

    detail_parts = [f"engine={engine or '-'}", f"chats={meta.get('chat_count', '-')}"]
    if meta.get("runtime_contract_version") is not None:
        detail_parts.append(f"contract=v{meta.get('runtime_contract_version')}")
    if meta.get("runtime_config_key") is not None:
        detail_parts.append(f"runtime_key={meta.get('runtime_config_key')}")
    if meta.get("configured_action_count") is not None:
        detail_parts.append(f"actions={meta.get('configured_action_count')}")
    _append_runtime_budget_detail_parts(meta, detail_parts)
    if missing_recommended:
        detail_parts.append("legacy_snapshot_missing=" + ",".join(missing_recommended))
    return RuntimeSnapshotValidation(
        valid=valid,
        engine=engine,
        missing_required=missing_required,
        missing_recommended=missing_recommended,
        detail_parts=tuple(detail_parts),
    )


def validate_worker_execution_snapshot(meta: Dict[str, Any]) -> RuntimeSnapshotValidation:
    if not isinstance(meta, dict):
        meta = {}
    engine = str(meta.get("engine") or "")
    missing_required = tuple(key for key in WORKER_REQUIRED_FIELDS if key not in meta)
    missing_recommended = tuple(key for key in WORKER_RECOMMENDED_FIELDS if key not in meta)
    valid = not missing_required and engine == EVENT_ENGINE_NAME

    detail_parts = [
        f"engine={engine or '-'}",
        f"updates={'on' if meta.get('requires_updates') else 'off'}",
        f"attempts={meta.get('total_attempts', '-')}",
        f"retries={meta.get('retry_count', '-')}",
        f"session_retries={meta.get('session_retry_count', '-')}",
    ]
    if meta.get("runtime_contract_version") is not None:
        detail_parts.append(f"contract=v{meta.get('runtime_contract_version')}")
    if meta.get("runtime_config_key") is not None:
        detail_parts.append(f"runtime_key={meta.get('runtime_config_key')}")
    if meta.get("task_timeout_seconds") is not None:
        detail_parts.append(f"task_timeout={meta.get('task_timeout_seconds')}s")
    if meta.get("chat_count") is not None:
        detail_parts.append(f"chats={meta.get('chat_count')}")
    if meta.get("configured_action_count") is not None:
        detail_parts.append(f"actions={meta.get('configured_action_count')}")
    _append_runtime_budget_detail_parts(meta, detail_parts)
    if missing_recommended:
        detail_parts.append("legacy_snapshot_missing=" + ",".join(missing_recommended))
    return RuntimeSnapshotValidation(
        valid=valid,
        engine=engine,
        missing_required=missing_required,
        missing_recommended=missing_recommended,
        detail_parts=tuple(detail_parts),
    )


def validate_event_final_state_snapshot(meta: Dict[str, Any]) -> RuntimeSnapshotValidation:
    if not isinstance(meta, dict):
        meta = {}
    status = str(meta.get("status") or "")
    current = any(key in meta for key in EVENT_FINAL_STATE_CURRENT_MARKERS)
    if not current:
        return RuntimeSnapshotValidation(
            valid=True,
            engine=status,
            missing_recommended=EVENT_FINAL_STATE_OBSERVABILITY_FIELDS,
            detail_parts=("legacy_or_compact_final_state", f"status={status or '-'}"),
            current=False,
        )

    missing_required = tuple(
        key for key in EVENT_FINAL_STATE_OBSERVABILITY_FIELDS if key not in meta
    )
    detail_parts = [
        f"status={status or '-'}",
        f"messages={meta.get('processed_versions', '-')}/{meta.get('processing_versions', '-')}",
        f"callbacks={meta.get('callback_confirmed', '-')}/{meta.get('callback_unconfirmed', '-')}",
        f"history={meta.get('history_rescue_scans', '-')}/{meta.get('history_failed_scans', '-')}",
        f"retry_remaining={meta.get('retry_budget_remaining', '-')}",
    ]
    if missing_required:
        detail_parts.append("missing=" + ",".join(missing_required))
    return RuntimeSnapshotValidation(
        valid=not missing_required,
        engine=status,
        missing_required=missing_required,
        detail_parts=tuple(detail_parts),
        current=True,
    )


def validate_button_callback_result_snapshot(meta: Dict[str, Any]) -> RuntimeSnapshotValidation:
    if not isinstance(meta, dict):
        meta = {}
    status = str(meta.get("callback_status") or "")
    missing_required = tuple(
        key for key in EVENT_BUTTON_CALLBACK_RESULT_OBSERVABILITY_FIELDS if key not in meta
    )
    missing_recommended = tuple(
        key for key in EVENT_BUTTON_CALLBACK_RESULT_RECOMMENDED_FIELDS if key not in meta
    )
    detail_parts = [
        f"status={status or '-'}",
        f"confirmed={str(bool(meta.get('confirmed'))).lower()}",
        f"attempt={meta.get('callback_attempt', '-')}/{meta.get('callback_max_retries', '-')}",
        f"timeout={meta.get('callback_timeout', '-')}",
        f"error={meta.get('callback_error_type', '-')}",
        f"had_timeout={str(bool(meta.get('callback_had_timeout'))).lower()}",
        f"index={meta.get('current_response_index', '-')}",
        f"action={meta.get('current_action', '-')}",
        f"retry_pending={str(bool(meta.get('retry_pending'))).lower()}",
        f"retry_remaining={meta.get('retry_budget_remaining', '-')}",
    ]
    if missing_required:
        detail_parts.append("missing=" + ",".join(missing_required))
    if missing_recommended:
        detail_parts.append("missing_recommended=" + ",".join(missing_recommended))
    return RuntimeSnapshotValidation(
        valid=not missing_required,
        engine=status,
        missing_required=missing_required,
        missing_recommended=missing_recommended,
        detail_parts=tuple(detail_parts),
    )


def validate_button_callback_released_snapshot(
    meta: Dict[str, Any],
) -> RuntimeSnapshotValidation:
    if not isinstance(meta, dict):
        meta = {}
    status = str(meta.get("callback_status") or "")
    missing_required = tuple(
        key for key in EVENT_BUTTON_CALLBACK_RELEASED_OBSERVABILITY_FIELDS if key not in meta
    )
    detail_parts = [
        f"status={status or '-'}",
        f"button={meta.get('button_text') or '-'}",
        f"source={meta.get('source') or '-'}",
        f"attempt_epoch={meta.get('attempt_epoch', '-')}",
        f"index={meta.get('current_response_index', '-')}",
        f"action={meta.get('current_action', '-')}",
        f"retry_count={meta.get('retry_count', '-')}",
        f"retry_pending={str(bool(meta.get('retry_pending'))).lower()}",
        f"retry_remaining={meta.get('retry_budget_remaining', '-')}",
        f"attempt={meta.get('callback_attempt', '-')}/{meta.get('callback_max_retries', '-')}",
        f"timeout={meta.get('callback_timeout', '-')}",
        f"had_timeout={str(bool(meta.get('callback_had_timeout'))).lower()}",
        f"clicked_versions={meta.get('clicked_versions', '-')}",
        f"released={str(bool(meta.get('released_for_retry'))).lower()}",
    ]
    if missing_required:
        detail_parts.append("missing=" + ",".join(missing_required))
    return RuntimeSnapshotValidation(
        valid=not missing_required,
        engine=status,
        missing_required=missing_required,
        detail_parts=tuple(detail_parts),
    )


def validate_button_callback_unconfirmed_snapshot(
    meta: Dict[str, Any],
) -> RuntimeSnapshotValidation:
    if not isinstance(meta, dict):
        meta = {}
    status = str(meta.get("callback_status") or "")
    missing_required = tuple(
        key for key in EVENT_BUTTON_CALLBACK_UNCONFIRMED_OBSERVABILITY_FIELDS if key not in meta
    )
    detail_parts = [
        f"status={status or '-'}",
        f"button={meta.get('button_text') or '-'}",
        f"source={meta.get('source') or '-'}",
        f"attempt_epoch={meta.get('attempt_epoch', '-')}",
        f"index={meta.get('current_response_index', '-')}",
        f"action={meta.get('current_action', '-')}",
        f"retry_count={meta.get('retry_count', '-')}",
        f"retry_pending={str(bool(meta.get('retry_pending'))).lower()}",
        f"retry_remaining={meta.get('retry_budget_remaining', '-')}",
        f"attempt={meta.get('callback_attempt', '-')}/{meta.get('callback_max_retries', '-')}",
        f"timeout={meta.get('callback_timeout', '-')}",
        f"error={meta.get('callback_error_type', '-')}",
        f"had_timeout={str(bool(meta.get('callback_had_timeout'))).lower()}",
    ]
    if missing_required:
        detail_parts.append("missing=" + ",".join(missing_required))
    return RuntimeSnapshotValidation(
        valid=not missing_required,
        engine=status,
        missing_required=missing_required,
        detail_parts=tuple(detail_parts),
    )


def validate_history_scan_completed_snapshot(meta: Dict[str, Any]) -> RuntimeSnapshotValidation:
    if not isinstance(meta, dict):
        meta = {}
    status = str(meta.get("status") or "")
    missing_required = tuple(
        key for key in EVENT_HISTORY_SCAN_COMPLETED_OBSERVABILITY_FIELDS if key not in meta
    )
    detail_parts = [
        f"source={meta.get('source') or '-'}",
        f"status={status or '-'}",
        f"messages={meta.get('message_count', '-')}",
        f"allowed={meta.get('allowed_count', '-')}",
        f"handled={meta.get('handled_count', '-')}",
    ]
    if missing_required:
        detail_parts.append("missing=" + ",".join(missing_required))
    return RuntimeSnapshotValidation(
        valid=not missing_required,
        engine=status,
        missing_required=missing_required,
        detail_parts=tuple(detail_parts),
    )


def validate_history_scan_cancelled_snapshot(meta: Dict[str, Any]) -> RuntimeSnapshotValidation:
    if not isinstance(meta, dict):
        meta = {}
    status = str(meta.get("status") or "")
    missing_required = tuple(
        key for key in EVENT_HISTORY_SCAN_CANCELLED_OBSERVABILITY_FIELDS if key not in meta
    )
    detail_parts = [
        f"source={meta.get('source') or '-'}",
        f"status={status or '-'}",
        f"messages={meta.get('message_count', '-')}",
        f"allowed={meta.get('allowed_count', '-')}",
        f"handled={meta.get('handled_count', '-')}",
        f"error={meta.get('error_type') or '-'}",
        f"cancelled_scans={meta.get('cancelled_scans', '-')}",
        f"scan_in_progress={str(bool(meta.get('scan_in_progress'))).lower()}",
        f"blocks_main_flow={str(bool(meta.get('blocks_main_flow'))).lower()}",
        f"retry_pending={str(bool(meta.get('retry_pending'))).lower()}",
    ]
    if missing_required:
        detail_parts.append("missing=" + ",".join(missing_required))
    return RuntimeSnapshotValidation(
        valid=not missing_required,
        engine=status,
        missing_required=missing_required,
        detail_parts=tuple(detail_parts),
    )


def validate_history_failed_snapshot(meta: Dict[str, Any]) -> RuntimeSnapshotValidation:
    if not isinstance(meta, dict):
        meta = {}
    error_type = str(meta.get("error_type") or "")
    missing_required = tuple(
        key for key in EVENT_HISTORY_FAILED_OBSERVABILITY_FIELDS if key not in meta
    )
    detail_parts = [
        f"source={meta.get('source') or '-'}",
        f"operation={meta.get('operation') or '-'}",
        f"timeout_scope={meta.get('timeout_scope') or '-'}",
        f"error={error_type or '-'}",
        f"timeout={meta.get('timeout', '-')}",
        f"operation_timeout={meta.get('operation_timeout', '-')}",
        f"failed_scans={meta.get('failed_scans', '-')}",
        f"consecutive_failures={meta.get('consecutive_failures', '-')}",
        f"failure_threshold={meta.get('failure_threshold', '-')}",
        f"rescue={str(bool(meta.get('rescue'))).lower()}",
        f"will_open_circuit={str(bool(meta.get('will_open_circuit'))).lower()}",
        f"rescue_suspended={str(bool(meta.get('rescue_suspended'))).lower()}",
        f"rescue_will_continue={str(bool(meta.get('rescue_will_continue'))).lower()}",
        f"scan_in_progress={str(bool(meta.get('scan_in_progress'))).lower()}",
        f"blocks_main_flow={str(bool(meta.get('blocks_main_flow'))).lower()}",
        f"retry_pending={str(bool(meta.get('retry_pending'))).lower()}",
    ]
    if missing_required:
        detail_parts.append("missing=" + ",".join(missing_required))
    return RuntimeSnapshotValidation(
        valid=not missing_required,
        engine=error_type,
        missing_required=missing_required,
        detail_parts=tuple(detail_parts),
    )


def validate_retry_event_snapshot(
    meta: Dict[str, Any],
    *,
    event_name: str,
) -> RuntimeSnapshotValidation:
    if not isinstance(meta, dict):
        meta = {}
    missing_required = [
        key for key in EVENT_RETRY_EVENT_OBSERVABILITY_FIELDS if key not in meta
    ]
    missing_required.extend(
        key
        for key in EVENT_RETRY_EVENT_EXTRA_FIELDS.get(event_name, ())
        if key not in meta
    )
    missing_recommended = tuple(
        key for key in EVENT_RETRY_EVENT_RECOMMENDED_FIELDS if key not in meta
    )
    detail_parts = [
        f"retry={meta.get('retry_count', '-')}",
        f"max={meta.get('max_inline_retries', '-')}",
        f"remaining={meta.get('retry_budget_remaining', '-')}",
        f"reason={meta.get('reason', '-')}",
        f"epoch={meta.get('attempt_epoch', '-')}",
        f"index={meta.get('current_response_index', '-')}",
        f"action={meta.get('current_action', '-')}",
        f"retry_pending={str(bool(meta.get('retry_pending'))).lower()}",
    ]
    if "finished" in meta:
        detail_parts.append(f"finished={meta.get('finished')}")
    if "suppressed_count" in meta:
        detail_parts.append(f"suppressed={meta.get('suppressed_count')}")
    if "error_type" in meta:
        detail_parts.append(f"error_type={meta.get('error_type') or '-'}")
    if missing_required:
        detail_parts.append("missing=" + ",".join(missing_required))
    if missing_recommended:
        detail_parts.append("missing_recommended=" + ",".join(missing_recommended))
    return RuntimeSnapshotValidation(
        valid=not missing_required,
        engine=event_name,
        missing_required=tuple(missing_required),
        missing_recommended=missing_recommended,
        detail_parts=tuple(detail_parts),
    )


def validate_hard_timeout_late_snapshot(
    meta: Dict[str, Any],
    *,
    event_name: str,
) -> RuntimeSnapshotValidation:
    if not isinstance(meta, dict):
        meta = {}
    missing_required = [
        key for key in EVENT_HARD_TIMEOUT_LATE_OBSERVABILITY_FIELDS if key not in meta
    ]
    missing_required.extend(
        key
        for key in EVENT_HARD_TIMEOUT_LATE_EXTRA_FIELDS.get(event_name, ())
        if key not in meta
    )
    missing_recommended = tuple(
        key for key in EVENT_HARD_TIMEOUT_LATE_RECOMMENDED_FIELDS if key not in meta
    )
    detail_parts = [
        f"event={event_name}",
        f"operation={meta.get('operation') or '-'}",
        f"timeout_scope={meta.get('timeout_scope') or '-'}",
        f"timeout={meta.get('timeout', '-')}",
        f"source={meta.get('source') or '-'}",
        f"message_id={meta.get('message_id', '-')}",
        f"attempt_epoch={meta.get('attempt_epoch', '-')}",
        f"current_response_index={meta.get('current_response_index', '-')}",
        f"current_action={meta.get('current_action') or '-'}",
        f"retry_count={meta.get('retry_count', '-')}",
        f"retry_budget_remaining={meta.get('retry_budget_remaining', '-')}",
        f"retry_pending={str(bool(meta.get('retry_pending'))).lower()}",
        f"cancelled_by_parent={str(bool(meta.get('cancelled_by_parent'))).lower()}",
    ]
    if "error_type" in meta:
        detail_parts.append(f"error_type={meta.get('error_type') or '-'}")
    if missing_required:
        detail_parts.append("missing=" + ",".join(missing_required))
    if missing_recommended:
        detail_parts.append("missing_recommended=" + ",".join(missing_recommended))
    return RuntimeSnapshotValidation(
        valid=not missing_required,
        engine=event_name,
        missing_required=tuple(missing_required),
        missing_recommended=missing_recommended,
        detail_parts=tuple(detail_parts),
    )


def validate_message_skip_snapshot(meta: Dict[str, Any]) -> RuntimeSnapshotValidation:
    if not isinstance(meta, dict):
        meta = {}
    reason = str(meta.get("reason") or "")
    missing_required = tuple(
        key for key in EVENT_MESSAGE_SKIP_OBSERVABILITY_FIELDS if key not in meta
    )
    detail_parts = [
        f"reason={reason or '-'}",
        f"version={meta.get('message_version_hash') or '-'}",
        f"attempt_epoch={meta.get('attempt_epoch', '-')}",
        f"index={meta.get('current_response_index', '-')}",
        f"action={meta.get('current_action') or '-'}",
        f"retry_count={meta.get('retry_count', '-')}",
        f"retry_budget={meta.get('retry_budget_remaining', '-')}",
        f"retry_pending={str(bool(meta.get('retry_pending'))).lower()}",
        f"duplicate={meta.get('skipped_duplicate', '-')}",
        f"concurrent={meta.get('skipped_concurrent_duplicate', '-')}",
        f"finished={meta.get('skipped_finished', '-')}",
        f"non_inbound={meta.get('skipped_non_inbound', '-')}",
    ]
    if "outgoing" in meta:
        detail_parts.append(f"outgoing={str(bool(meta.get('outgoing'))).lower()}")
    if "from_self" in meta:
        detail_parts.append(f"from_self={str(bool(meta.get('from_self'))).lower()}")
    if missing_required:
        detail_parts.append("missing=" + ",".join(missing_required))
    return RuntimeSnapshotValidation(
        valid=not missing_required,
        engine=reason,
        missing_required=missing_required,
        detail_parts=tuple(detail_parts),
    )


def validate_message_unhandled_snapshot(meta: Dict[str, Any]) -> RuntimeSnapshotValidation:
    if not isinstance(meta, dict):
        meta = {}
    missing_required = tuple(
        key for key in EVENT_MESSAGE_UNHANDLED_OBSERVABILITY_FIELDS if key not in meta
    )
    detail_parts = [
        f"count={meta.get('unhandled_messages', '-')}",
        f"version={meta.get('message_version_hash') or '-'}",
        f"action={meta.get('current_action') or '-'}",
        f"index={meta.get('current_response_index', '-')}",
        f"retry_pending={str(bool(meta.get('retry_pending'))).lower()}",
        f"text={str(bool(meta.get('has_text'))).lower()}",
        f"photo={str(bool(meta.get('has_photo'))).lower()}",
        f"reply_markup={str(bool(meta.get('has_reply_markup'))).lower()}",
    ]
    if missing_required:
        detail_parts.append("missing=" + ",".join(missing_required))
    return RuntimeSnapshotValidation(
        valid=not missing_required,
        engine=str(meta.get("current_action") or ""),
        missing_required=missing_required,
        detail_parts=tuple(detail_parts),
    )


def validate_message_processing_cancelled_snapshot(
    meta: Dict[str, Any],
) -> RuntimeSnapshotValidation:
    if not isinstance(meta, dict):
        meta = {}
    missing_required = tuple(
        key
        for key in EVENT_MESSAGE_PROCESSING_CANCELLED_OBSERVABILITY_FIELDS
        if key not in meta
    )
    detail_parts = [
        f"count={meta.get('message_processing_cancelled', '-')}",
        f"version={meta.get('message_version_hash') or '-'}",
        f"message_epoch={meta.get('message_attempt_epoch', '-')}",
        f"attempt_epoch={meta.get('attempt_epoch', '-')}",
        f"action={meta.get('current_action') or '-'}",
        f"index={meta.get('current_response_index', '-')}",
        f"retry_pending={str(bool(meta.get('retry_pending'))).lower()}",
        f"processing_versions={meta.get('processing_versions', '-')}",
        f"will_release={str(bool(meta.get('will_release_processing_version'))).lower()}",
        f"finished={str(bool(meta.get('finished'))).lower()}",
    ]
    if missing_required:
        detail_parts.append("missing=" + ",".join(missing_required))
    return RuntimeSnapshotValidation(
        valid=not missing_required,
        engine=str(meta.get("current_action") or ""),
        missing_required=missing_required,
        detail_parts=tuple(detail_parts),
    )


def validate_worker_lock_event_snapshot(
    meta: Dict[str, Any],
    *,
    event_name: str,
) -> RuntimeSnapshotValidation:
    if not isinstance(meta, dict):
        meta = {}
    required_by_event = {
        "account_lock_wait_started": EVENT_WORKER_LOCK_WAIT_STARTED_FIELDS,
        "global_concurrency_wait_started": EVENT_WORKER_LOCK_WAIT_STARTED_FIELDS,
        "account_lock_acquired": EVENT_WORKER_LOCK_ACQUIRED_FIELDS,
        "global_concurrency_acquired": EVENT_WORKER_LOCK_ACQUIRED_FIELDS,
        "account_lock_wait_timeout": EVENT_WORKER_LOCK_WAIT_TIMEOUT_FIELDS,
        "global_concurrency_wait_timeout": EVENT_WORKER_LOCK_WAIT_TIMEOUT_FIELDS,
        "account_lock_released": EVENT_WORKER_LOCK_RELEASED_FIELDS,
        "global_concurrency_released": EVENT_WORKER_LOCK_RELEASED_FIELDS,
    }
    required_fields = required_by_event.get(event_name, ())
    missing_required = tuple(key for key in required_fields if key not in meta)
    detail_parts = [
        f"event={event_name}",
        f"operation={meta.get('operation') or '-'}",
        f"timeout_scope={meta.get('timeout_scope') or '-'}",
        f"wait={meta.get('wait_seconds', '-')}",
        f"timeout={meta.get('timeout_seconds', '-')}",
        f"locked={str(bool(meta.get('locked'))).lower()}",
        f"success={str(bool(meta.get('success'))).lower()}",
        f"attempt={meta.get('attempt', '-')}/{meta.get('total_attempts', '-')}",
    ]
    if missing_required:
        detail_parts.append("missing=" + ",".join(missing_required))
    return RuntimeSnapshotValidation(
        valid=not missing_required and bool(required_fields),
        engine=event_name,
        missing_required=missing_required,
        detail_parts=tuple(detail_parts),
    )


def validate_client_cleanup_event_snapshot(
    meta: Dict[str, Any],
    *,
    event_name: str,
) -> RuntimeSnapshotValidation:
    if not isinstance(meta, dict):
        meta = {}
    if event_name not in {
        "client_cleanup_started",
        "client_cleanup_completed",
        "client_cleanup_failed",
        "client_cleanup_late_cancelled",
        "client_cleanup_late_completed",
        "client_cleanup_late_exception",
        "task_cancellation_deferred_for_cleanup",
    }:
        return RuntimeSnapshotValidation(
            valid=False,
            engine=event_name,
            missing_required=EVENT_CLIENT_CLEANUP_BASE_FIELDS,
            detail_parts=(f"unknown_cleanup_event={event_name}",),
        )

    missing_required = [
        key for key in EVENT_CLIENT_CLEANUP_BASE_FIELDS if key not in meta
    ]
    missing_required.extend(
        key
        for key in EVENT_CLIENT_CLEANUP_FAILED_EXTRA_FIELDS
        if event_name == "client_cleanup_failed" and key not in meta
    )
    missing_required.extend(
        key
        for key in EVENT_CLIENT_CLEANUP_LATE_EXTRA_FIELDS.get(event_name, ())
        if key not in meta
    )
    missing_recommended = tuple(
        key
        for key in EVENT_CLIENT_CLEANUP_COMPLETED_RECOMMENDED_FIELDS
        if event_name == "client_cleanup_completed" and key not in meta
    )
    detail_parts = [
        f"event={event_name}",
        f"operation={meta.get('operation') or '-'}",
        f"timeout_scope={meta.get('timeout_scope') or '-'}",
        f"attempt={meta.get('attempt', '-')}/{meta.get('total_attempts', '-')}",
        f"success={str(bool(meta.get('success'))).lower()}",
        f"timeout={meta.get('timeout_seconds', '-')}",
        f"manager_lock={str(bool(meta.get('lock_present'))).lower()}/"
        f"{str(bool(meta.get('lock_acquired'))).lower()}",
        f"force_cleanup={str(bool(meta.get('force_cleanup'))).lower()}",
    ]
    if "error_type" in meta:
        detail_parts.append(f"error_type={meta.get('error_type') or '-'}")
    if missing_required:
        detail_parts.append("missing=" + ",".join(missing_required))
    if missing_recommended:
        detail_parts.append("missing_recommended=" + ",".join(missing_recommended))
    return RuntimeSnapshotValidation(
        valid=not missing_required,
        engine=event_name,
        missing_required=tuple(missing_required),
        missing_recommended=missing_recommended,
        detail_parts=tuple(detail_parts),
    )


def count_events(flow_items: Sequence[Dict[str, Any]], event_name: str) -> int:
    return sum(
        1
        for item in flow_items
        if isinstance(item, dict) and str(item.get("event") or "") == event_name
    )
