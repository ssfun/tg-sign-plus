from __future__ import annotations

import re
from typing import Any, Dict, Sequence

from backend.services.sign_task_runtime_contract import (
    EVENT_BOOLEAN_COUNT_FIELDS,
    EVENT_ENGINE_BUTTON_CALLBACK_RELEASED_FOR_RETRY,
    EVENT_ENGINE_CAPTCHA_RESULT_TEXT_PREEMPTED,
    EVENT_ENGINE_HARD_TIMEOUT_LATE_CANCELLED,
    EVENT_ENGINE_HARD_TIMEOUT_LATE_COMPLETED,
    EVENT_ENGINE_HARD_TIMEOUT_LATE_EXCEPTION,
    EVENT_ENGINE_MESSAGE_PROCESSING_CANCELLED,
    EVENT_NUMERIC_BUDGET_FIELDS,
    EVENT_RUNTIME_SHAPE_SUMMARY_FIELDS,
)

_SENSITIVE_ERROR_PATTERNS = (
    (re.compile(r"(?i)(chat[_\s-]*id\s*[:=]\s*)-?\d+"), r"\1<redacted>"),
    (re.compile(r"(?i)(account[_\s-]*name\s*[:=]\s*)[^\s,;，。)]+"), r"\1<redacted>"),
    (re.compile(r"(?i)(task[_\s-]*name\s*[:=]\s*)[^\s,;，。)]+"), r"\1<redacted>"),
    (re.compile(r"(账号[:：]?\s*)[^\s,;，。)]+"), r"\1<redacted>"),
    (re.compile(r"(任务[:：]?\s*)[^\s,;，。)]+"), r"\1<redacted>"),
)


def _event(item: Dict[str, Any]) -> str:
    return str(item.get("event") or "")


def _meta(item: Dict[str, Any]) -> Dict[str, Any]:
    meta = item.get("meta")
    return meta if isinstance(meta, dict) else {}


def _last_meta(items: Sequence[Dict[str, Any]], event_name: str) -> Dict[str, Any]:
    for item in reversed(items):
        if _event(item) == event_name:
            return _meta(item)
    return {}


def _last_event_meta(
    items: Sequence[Dict[str, Any]],
    event_names: set[str],
) -> tuple[str, Dict[str, Any]]:
    for item in reversed(items):
        event_name = _event(item)
        if event_name in event_names:
            return event_name, _meta(item)
    return "", {}


def _result_status_from_match_event(event_name: str) -> str:
    if event_name == "event_engine_checked_matched":
        return "checked"
    if event_name == "event_engine_success_matched":
        return "success"
    if event_name == "event_engine_failed_matched":
        return "failed"
    return ""


def _count(items: Sequence[Dict[str, Any]], event_name: str) -> int:
    return sum(1 for item in items if _event(item) == event_name)


def _has_event(items: Sequence[Dict[str, Any]], event_name: str) -> bool:
    return any(_event(item) == event_name for item in items)


def build_flow_event_counts(
    flow_items: Sequence[Dict[str, Any]] | None,
) -> Dict[str, int]:
    """Count structured worker events without exposing task-specific content."""

    counts: Dict[str, int] = {}
    for item in flow_items or []:
        if not isinstance(item, dict):
            continue
        event_name = _event(item)
        if not event_name:
            continue
        counts[event_name] = counts.get(event_name, 0) + 1
    return counts


def _count_callback_results(
    items: Sequence[Dict[str, Any]],
    *,
    status: str | None = None,
    confirmed: bool | None = None,
) -> int:
    count = 0
    for item in items:
        if _event(item) != "event_engine_button_callback_result":
            continue
        meta = _meta(item)
        if status is not None and str(meta.get("callback_status") or "") != status:
            continue
        if confirmed is not None and bool(meta.get("confirmed")) is not confirmed:
            continue
        count += 1
    return count


def _last_callback_meta(items: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    return _last_meta(items, "event_engine_button_callback_result")


def _count_message_skips(items: Sequence[Dict[str, Any]], reason: str) -> int:
    return sum(
        1
        for item in items
        if _event(item) == "event_engine_message_skip_recorded"
        and str(_meta(item).get("reason") or "") == reason
    )


def _snapshot_int_or_event_count(
    final_state: Dict[str, Any],
    timeout_state: Dict[str, Any],
    key: str,
    fallback: int,
) -> int:
    if key in final_state:
        return _safe_int(final_state.get(key), 0)
    if key in timeout_state:
        return _safe_int(timeout_state.get(key), 0)
    return fallback


def _snapshot_bool_or_event_flag(
    final_state: Dict[str, Any],
    timeout_state: Dict[str, Any],
    key: str,
    fallback: bool,
) -> bool:
    if key in final_state:
        return bool(final_state.get(key))
    if key in timeout_state:
        return bool(timeout_state.get(key))
    return fallback


def _snapshot_value(
    final_state: Dict[str, Any],
    timeout_state: Dict[str, Any],
    key: str,
    default: Any = None,
) -> Any:
    if key in final_state:
        return final_state.get(key)
    if key in timeout_state:
        return timeout_state.get(key)
    return default


def _runtime_value(
    final_state: Dict[str, Any],
    timeout_state: Dict[str, Any],
    worker_contract: Dict[str, Any],
    key: str,
    *,
    contract_key: str | None = None,
    default: Any = None,
) -> Any:
    value = _snapshot_value(final_state, timeout_state, key, None)
    if value is not None:
        return value
    source_key = contract_key or key
    if source_key in worker_contract:
        return worker_contract.get(source_key)
    return default


def _runtime_budget_summary(
    final_state: Dict[str, Any],
    timeout_state: Dict[str, Any],
    worker_contract: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        field.summary_key: _runtime_value(
            final_state,
            timeout_state,
            worker_contract,
            field.state_key,
            contract_key=field.snapshot_key,
        )
        for field in EVENT_NUMERIC_BUDGET_FIELDS
    }


def _runtime_boolean_count_summary(worker_contract: Dict[str, Any]) -> Dict[str, Any]:
    return {
        field.summary_enabled_key: worker_contract.get(field.enabled_count_key)
        for field in EVENT_BOOLEAN_COUNT_FIELDS
    } | {
        field.summary_disabled_key: worker_contract.get(field.disabled_count_key)
        for field in EVENT_BOOLEAN_COUNT_FIELDS
    }


def _runtime_shape_summary(worker_contract: Dict[str, Any]) -> Dict[str, Any]:
    return {
        field: worker_contract.get(field)
        for field in EVENT_RUNTIME_SHAPE_SUMMARY_FIELDS
    }


def _last_int_from_event(items: Sequence[Dict[str, Any]], event_name: str, key: str) -> int:
    return _safe_int(_last_meta(items, event_name).get(key), 0)


_RETRY_EVENTS = {
    "event_engine_retry_scheduled",
    "event_engine_retry_started",
    "event_engine_retry_completed",
    "event_engine_retry_cancelled",
    "event_engine_retry_suppressed",
    "event_engine_retry_initial_send_failed",
    "event_engine_retry_initial_send_error",
    "event_engine_retry_limit_exceeded",
}


_RPC_TIMEOUT_EVENTS = {
    "event_engine_initial_send_retryable_error": "send",
    "event_engine_followup_send_retryable_error": "send",
    "event_engine_response_send_retryable_error": "send",
    "event_engine_media_download_retryable_error": "media",
    "event_engine_ai_retryable_error": "ai",
    "event_engine_button_callback_outer_timeout": "callback",
    "event_engine_history_failed": "history",
    "client_rpc_hard_timeout": "client",
    "client_startup_lock_timeout": "client_lock",
    "client_exit_lock_timeout": "client_lock",
    "client_close_lock_timeout": "client_lock",
}
_CLIENT_RPC_LATE_EVENTS = {
    "client_rpc_late_cancelled",
    "client_rpc_late_completed",
    "client_rpc_late_exception",
}


_HARD_TIMEOUT_LATE_EVENTS = {
    EVENT_ENGINE_HARD_TIMEOUT_LATE_CANCELLED,
    EVENT_ENGINE_HARD_TIMEOUT_LATE_COMPLETED,
    EVENT_ENGINE_HARD_TIMEOUT_LATE_EXCEPTION,
}
_TASK_RUN_LATE_EVENTS = {
    "task_run_late_cancelled",
    "task_run_late_completed",
    "task_run_late_exception",
}


def _last_rpc_timeout_meta(items: Sequence[Dict[str, Any]]) -> tuple[str, str, Dict[str, Any]]:
    for item in reversed(items):
        event_name = _event(item)
        rpc_kind = _RPC_TIMEOUT_EVENTS.get(event_name)
        if rpc_kind is None:
            continue
        meta = _meta(item)
        if event_name == "client_rpc_hard_timeout" and _is_client_cleanup_rpc_meta(meta):
            rpc_kind = "client_cleanup"
        return event_name, rpc_kind, meta
    return "", "", {}


def _last_hard_timeout_late_meta(items: Sequence[Dict[str, Any]]) -> tuple[str, Dict[str, Any]]:
    for item in reversed(items):
        event_name = _event(item)
        if event_name in _HARD_TIMEOUT_LATE_EVENTS:
            return event_name, _meta(item)
    return "", {}


def _last_task_run_late_meta(items: Sequence[Dict[str, Any]]) -> tuple[str, Dict[str, Any]]:
    for item in reversed(items):
        event_name = _event(item)
        if event_name in _TASK_RUN_LATE_EVENTS:
            return event_name, _meta(item)
    return "", {}


def _last_client_rpc_late_meta(items: Sequence[Dict[str, Any]]) -> tuple[str, Dict[str, Any]]:
    for item in reversed(items):
        event_name = _event(item)
        if event_name in _CLIENT_RPC_LATE_EVENTS:
            return event_name, _meta(item)
    return "", {}


def _is_client_cleanup_rpc_meta(meta: Dict[str, Any]) -> bool:
    return (
        str(meta.get("timeout_scope") or "") == "client_cleanup"
        or str(meta.get("operation") or "") == "cleanup_step"
    )


def _count_client_cleanup_rpc_timeouts(items: Sequence[Dict[str, Any]]) -> int:
    return sum(
        1
        for item in items
        if _event(item) == "client_rpc_hard_timeout"
        and _is_client_cleanup_rpc_meta(_meta(item))
    )


def _timeout_count_total(items: Sequence[Dict[str, Any]], *, client_cleanup_rpc_timeouts: int) -> int:
    return (
        _count(items, "event_engine_timeout_state")
        + _count(items, "event_engine_response_action_timeout")
        + _count(items, "event_engine_initial_send_retryable_error")
        + _count(items, "event_engine_followup_send_retryable_error")
        + _count(items, "event_engine_response_send_retryable_error")
        + _count(items, "event_engine_media_download_retryable_error")
        + _count(items, "event_engine_ai_retryable_error")
        + _count(items, "event_engine_button_callback_outer_timeout")
        + _count(items, "task_run_timeout")
        + _count(items, "client_rpc_hard_timeout")
        + _count(items, "client_rpc_late_cancelled")
        + _count(items, "client_rpc_late_completed")
        + _count(items, "client_rpc_late_exception")
        + _count(items, "client_startup_retry_scheduled")
        + _count(items, "client_startup_lock_timeout")
        + _count(items, "client_exit_lock_timeout")
        + _count(items, "client_close_lock_timeout")
        + _count(items, "task_run_late_cancelled")
        + _count(items, "task_run_late_completed")
        + _count(items, "task_run_late_exception")
        + _count(items, EVENT_ENGINE_HARD_TIMEOUT_LATE_CANCELLED)
        + _count(items, EVENT_ENGINE_HARD_TIMEOUT_LATE_COMPLETED)
        + _count(items, EVENT_ENGINE_HARD_TIMEOUT_LATE_EXCEPTION)
    )


def _last_client_cleanup_rpc_timeout_meta(items: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    for item in reversed(items):
        if _event(item) != "client_rpc_hard_timeout":
            continue
        meta = _meta(item)
        if _is_client_cleanup_rpc_meta(meta):
            return meta
    return {}


def _count_client_cleanup_rpc_late(
    items: Sequence[Dict[str, Any]],
    event_name: str,
) -> int:
    return sum(
        1
        for item in items
        if _event(item) == event_name
        and _is_client_cleanup_rpc_meta(_meta(item))
    )


def _last_client_cleanup_rpc_late_meta(items: Sequence[Dict[str, Any]]) -> tuple[str, Dict[str, Any]]:
    for item in reversed(items):
        event_name = _event(item)
        if event_name not in _CLIENT_RPC_LATE_EVENTS:
            continue
        meta = _meta(item)
        if _is_client_cleanup_rpc_meta(meta):
            return event_name, meta
    return "", {}


_CLIENT_CLEANUP_LATE_EVENTS = {
    "client_cleanup_late_cancelled",
    "client_cleanup_late_completed",
    "client_cleanup_late_exception",
}


def _last_client_cleanup_late_meta(items: Sequence[Dict[str, Any]]) -> tuple[str, Dict[str, Any]]:
    for item in reversed(items):
        event_name = _event(item)
        if event_name in _CLIENT_CLEANUP_LATE_EVENTS:
            return event_name, _meta(item)
    return "", {}


def _last_int_from_events(
    items: Sequence[Dict[str, Any]],
    event_names: set[str],
    key: str,
) -> int:
    for item in reversed(items):
        if _event(item) not in event_names:
            continue
        meta = _meta(item)
        if key in meta:
            return _safe_int(meta.get(key), 0)
    return 0


def _last_retry_meta(items: Sequence[Dict[str, Any]]) -> tuple[str, Dict[str, Any]]:
    for item in reversed(items):
        event_name = _event(item)
        if event_name in _RETRY_EVENTS:
            return event_name, _meta(item)
    return "", {}


def _last_history_scan_meta(items: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    for item in reversed(items):
        event_name = _event(item)
        meta = _meta(item)
        if event_name == "event_engine_history_scan_completed":
            status = meta.get("status")
            if not status:
                status = "handled" if _safe_int(meta.get("handled_count"), 0) > 0 else "idle"
            return {
                "source": meta.get("source"),
                "status": status,
                "message_count": meta.get("message_count"),
                "allowed_count": meta.get("allowed_count"),
                "handled_count": meta.get("handled_count"),
                "error_type": "",
                "attempt_epoch": meta.get("attempt_epoch"),
                "current_response_index": meta.get("current_response_index"),
                "current_action": meta.get("current_action"),
                "retry_count": meta.get("retry_count"),
                "retry_budget_remaining": meta.get("retry_budget_remaining"),
                "retry_pending": meta.get("retry_pending"),
            }
        if event_name == "event_engine_history_hard_failure_skipped":
            return {
                "source": meta.get("source") or "startup",
                "status": "skipped_failure",
                "message_count": meta.get("message_count"),
                "allowed_count": meta.get("allowed_count"),
                "handled_count": 1,
                "error_type": "",
            }
        if event_name == "event_engine_history_failed":
            return {
                "source": meta.get("source"),
                "status": "failed",
                "message_count": meta.get("message_count"),
                "allowed_count": meta.get("allowed_count"),
                "handled_count": meta.get("handled_count"),
                "error_type": meta.get("error_type"),
                "attempt_epoch": meta.get("attempt_epoch"),
                "current_response_index": meta.get("current_response_index"),
                "current_action": meta.get("current_action"),
                "retry_count": meta.get("retry_count"),
                "retry_budget_remaining": meta.get("retry_budget_remaining"),
                "retry_pending": meta.get("retry_pending"),
            }
        if event_name == "event_engine_history_scan_concurrent_skipped":
            return {
                "source": meta.get("source"),
                "status": meta.get("status") or "concurrent_skipped",
                "message_count": 0,
                "allowed_count": 0,
                "handled_count": 0,
                "error_type": "",
                "attempt_epoch": meta.get("attempt_epoch"),
                "current_response_index": meta.get("current_response_index"),
                "current_action": meta.get("current_action"),
                "retry_count": meta.get("retry_count"),
                "retry_budget_remaining": meta.get("retry_budget_remaining"),
                "retry_pending": meta.get("retry_pending"),
            }
        if event_name == "event_engine_history_scan_cancelled":
            return {
                "source": meta.get("source"),
                "status": meta.get("status") or "cancelled",
                "message_count": meta.get("message_count"),
                "allowed_count": meta.get("allowed_count"),
                "handled_count": meta.get("handled_count"),
                "error_type": meta.get("error_type") or "CancelledError",
                "attempt_epoch": meta.get("attempt_epoch"),
                "current_response_index": meta.get("current_response_index"),
                "current_action": meta.get("current_action"),
                "retry_count": meta.get("retry_count"),
                "retry_budget_remaining": meta.get("retry_budget_remaining"),
                "retry_pending": meta.get("retry_pending"),
            }
        if event_name == "event_engine_history_rescue_cancelled":
            return {
                "source": meta.get("source") or "rescue",
                "status": meta.get("status") or "cancelled",
                "message_count": 0,
                "allowed_count": 0,
                "handled_count": 0,
                "error_type": "CancelledError",
                "attempt_epoch": meta.get("attempt_epoch"),
                "current_response_index": meta.get("current_response_index"),
                "current_action": meta.get("current_action"),
                "retry_count": meta.get("retry_count"),
                "retry_budget_remaining": meta.get("retry_budget_remaining"),
                "retry_pending": meta.get("retry_pending"),
            }
    return {}


def _sum_meta_int(items: Sequence[Dict[str, Any]], event_name: str, key: str) -> int:
    total = 0
    for item in items:
        if _event(item) == event_name:
            total += _safe_int(_meta(item).get(key), 0)
    return total


def _max_meta_int(items: Sequence[Dict[str, Any]], event_name: str, key: str) -> int:
    values = [
        _safe_int(_meta(item).get(key), 0)
        for item in items
        if _event(item) == event_name
    ]
    return max(values, default=0)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _sanitize_public_error(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    for pattern, replacement in _SENSITIVE_ERROR_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def sanitize_public_run_summary(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    if not isinstance(summary, dict):
        return {}
    sanitized: Dict[str, Any] = {}
    for key, value in summary.items():
        normalized_key = str(key)
        if isinstance(value, dict):
            sanitized[normalized_key] = sanitize_public_run_summary(value)
        elif isinstance(value, str):
            sanitized[normalized_key] = _sanitize_public_error(value)
        else:
            sanitized[normalized_key] = value
    return sanitized


def build_run_summary(
    flow_items: Sequence[Dict[str, Any]] | None, *, success: bool, error: str = ""
) -> Dict[str, Any]:
    """Build a generic API/control-plane summary from worker events.

    The summary intentionally avoids task names, account names, chat ids, bot
    names, and message text. It is safe to return from API endpoints and cache in
    last-run metadata while detailed diagnostics remain available from
    ``flow_items``.
    """
    items = [item for item in flow_items or [] if isinstance(item, dict)]
    final_state = _last_meta(items, "event_engine_final_state")
    timeout_state = _last_meta(items, "event_engine_timeout_state")
    task_completed = _last_meta(items, "task_completed")
    task_failed = _last_meta(items, "task_failed")
    worker_contract = _last_meta(items, "worker_execution_contract")
    run_info_save_failed = _last_meta(items, "task_run_info_save_failed")
    final_status = _normalize_status(final_state.get("status"))
    if not final_status:
        if _has_event(items, "event_engine_checked_matched"):
            final_status = "checked"
        elif _has_event(items, "event_engine_success_matched"):
            final_status = "success"
        elif _has_event(items, "event_engine_failed_matched") or _has_event(
            items, "task_failed"
        ):
            final_status = "failed"
        else:
            final_status = "success" if success else "failed"
    attempt = _safe_int(
        task_completed.get("attempt")
        or task_failed.get("attempt")
        or final_state.get("retry_count"),
        0,
    )
    total_attempts = _safe_int(
        task_completed.get("total_attempts")
        or task_failed.get("total_attempts")
        or worker_contract.get("total_attempts"),
        0,
    )
    retry_count_fallback = max(
        _max_meta_int(items, "event_engine_retry_scheduled", "retry_count"),
        _max_meta_int(items, "event_engine_retry_started", "retry_count"),
        _max_meta_int(items, "event_engine_retry_completed", "retry_count"),
        _max_meta_int(items, "event_engine_retry_cancelled", "retry_count"),
        _max_meta_int(items, "event_engine_retry_suppressed", "retry_count"),
        _max_meta_int(items, "event_engine_retry_initial_send_failed", "retry_count"),
        _max_meta_int(items, "event_engine_retry_initial_send_error", "retry_count"),
        _max_meta_int(items, "event_engine_retry_limit_exceeded", "retry_count"),
    )
    retry_budget_remaining_fallback = _last_int_from_events(
        items, _RETRY_EVENTS, "retry_budget_remaining"
    )
    retry_suppressed_fallback = max(
        _count(items, "event_engine_retry_suppressed"),
        _last_int_from_event(
            items, "event_engine_retry_suppressed", "suppressed_count"
        ),
    )
    return {
        "success": bool(success),
        "status": final_status,
        "error": _sanitize_public_error(error),
        "attempt": attempt,
        "total_attempts": total_attempts,
        "task_timeout_seconds": worker_contract.get("task_timeout_seconds")
        or task_failed.get("timeout_seconds"),
        "requires_updates": worker_contract.get("requires_updates"),
        "current_response_index": _safe_int(
            _snapshot_value(final_state, timeout_state, "current_response_index", 0), 0
        ),
        "response_action_count": _safe_int(
            _snapshot_value(final_state, timeout_state, "response_action_count", 0), 0
        ),
        "current_action": str(
            _snapshot_value(final_state, timeout_state, "current_action", "") or ""
        ),
        "attempt_epoch": _safe_int(
            _snapshot_value(final_state, timeout_state, "attempt_epoch", 0), 0
        ),
        "result_match": _build_result_match_summary(items),
        "retry_count": _snapshot_int_or_event_count(
            final_state, timeout_state, "retry_count", retry_count_fallback
        ),
        "retry_budget_remaining": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "retry_budget_remaining",
            retry_budget_remaining_fallback,
        ),
        "retry_suppressed_count": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "retry_suppressed_count",
            retry_suppressed_fallback,
        ),
        "retry": _build_retry_summary(items, final_state, timeout_state),
        "callbacks": _build_callbacks_summary(items, final_state, timeout_state),
        "messages": _build_messages_summary(items, final_state, timeout_state),
        "history": _build_history_summary(items, final_state, timeout_state),
        "timeouts": _build_timeouts_summary(items),
        "runtime": _build_runtime_summary(items, final_state, timeout_state),
        "cleanup": _build_cleanup_summary(items),
        "persistence": {
            "run_info_save_failed": bool(run_info_save_failed),
            "run_info_save_error_type": run_info_save_failed.get("error_type"),
        },
        "account_lock": _build_gate_summary(items, "account_lock"),
        "global_concurrency": _build_gate_summary(items, "global_concurrency"),
        "error_type": task_failed.get("error_type"),
        "error_timeout_scope": task_failed.get("timeout_scope"),
    }


def _build_result_match_summary(items) -> Dict[str, Any]:
    last_result_match_event, last_result_match = _last_event_meta(
        items,
        {
            "event_engine_checked_matched",
            "event_engine_success_matched",
            "event_engine_failed_matched",
        },
    )
    return {
        "event": last_result_match_event,
        "matched": bool(last_result_match_event),
        "status": _result_status_from_match_event(last_result_match_event),
        "source": str(last_result_match.get("source") or ""),
        "message_id": _safe_int(last_result_match.get("message_id"), 0),
        "keyword": str(last_result_match.get("keyword") or ""),
        "attempt_epoch": _safe_int(last_result_match.get("attempt_epoch"), 0),
        "current_response_index": _safe_int(
            last_result_match.get("current_response_index"),
            0,
        ),
        "current_action": str(last_result_match.get("current_action") or ""),
        "retry_count": _safe_int(last_result_match.get("retry_count"), 0),
        "retry_budget_remaining": _safe_int(
            last_result_match.get("retry_budget_remaining"),
            0,
        ),
        "retry_pending": bool(last_result_match.get("retry_pending")),
    }


def _build_retry_summary(items, final_state, timeout_state) -> Dict[str, Any]:
    last_task_retry_event, last_task_retry_meta = _last_event_meta(
        items,
        {
            "task_retry_config",
            "task_retry_started",
            "task_retry_scheduled",
        },
    )
    retry_suppressed_fallback = max(
        _count(items, "event_engine_retry_suppressed"),
        _last_int_from_event(
            items, "event_engine_retry_suppressed", "suppressed_count"
        ),
    )
    last_retry_event, last_retry_meta = _last_retry_meta(items)
    last_attempt_state_reset = _last_meta(items, "event_engine_attempt_state_reset")
    retry_limit_exceeded_meta = _last_meta(items, "event_engine_retry_limit_exceeded")
    return {
        "last_event": last_retry_event,
        "last_reason": str(last_retry_meta.get("reason") or ""),
        "last_retry_count": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "retry_count",
            _safe_int(last_retry_meta.get("retry_count"), 0),
        )
        if not last_retry_event
        else _safe_int(last_retry_meta.get("retry_count"), 0),
        "last_budget_remaining": _safe_int(
            last_retry_meta.get("retry_budget_remaining")
            if last_retry_event
            else _snapshot_value(
                final_state,
                timeout_state,
                "retry_budget_remaining",
                0,
            ),
            0,
        ),
        "last_attempt_epoch": _safe_int(last_retry_meta.get("attempt_epoch"), 0),
        "last_source": str(last_retry_meta.get("retry_source") or ""),
        "last_message_id": _safe_int(last_retry_meta.get("retry_message_id"), 0),
        "last_trigger": str(last_retry_meta.get("retry_trigger") or ""),
        "attempt_state_resets": _count(items, "event_engine_attempt_state_reset"),
        "last_reset_previous_attempt_epoch": _safe_int(
            last_attempt_state_reset.get("previous_attempt_epoch"),
            0,
        ),
        "last_reset_attempt_epoch": _safe_int(
            last_attempt_state_reset.get("attempt_epoch"),
            0,
        ),
        "last_reset_cleared_processed_versions": _safe_int(
            last_attempt_state_reset.get("cleared_processed_versions"),
            0,
        ),
        "last_reset_cleared_sent_captcha_versions": _safe_int(
            last_attempt_state_reset.get("cleared_sent_captcha_versions"),
            0,
        ),
        "last_reset_cleared_clicked_versions": _safe_int(
            last_attempt_state_reset.get("cleared_clicked_versions"),
            0,
        ),
        "last_reset_cleared_history_duplicates": _safe_int(
            last_attempt_state_reset.get("cleared_history_duplicates"),
            0,
        ),
        "last_reset_cleared_history_filtered": _safe_int(
            last_attempt_state_reset.get("cleared_history_filtered"),
            0,
        ),
        "last_reset_cleared_history_unhandled": _safe_int(
            last_attempt_state_reset.get("cleared_history_unhandled"),
            0,
        ),
        "last_reset_cleared_history_unhandled_duplicates": _safe_int(
            last_attempt_state_reset.get("cleared_history_unhandled_duplicates"),
            0,
        ),
        "last_reset_cleared_history_tracked_message_ids": _safe_int(
            last_attempt_state_reset.get("cleared_history_tracked_message_ids"),
            0,
        ),
        "last_current_response_index": _safe_int(
            last_retry_meta.get("current_response_index"),
            0,
        ),
        "last_current_action": str(last_retry_meta.get("current_action") or ""),
        "last_retry_pending": bool(last_retry_meta.get("retry_pending")),
        "scheduled_count": _count(items, "event_engine_retry_scheduled"),
        "started_count": _count(items, "event_engine_retry_started"),
        "completed_count": _count(items, "event_engine_retry_completed"),
        "cancelled_count": _count(items, "event_engine_retry_cancelled"),
        "suppressed_count": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "retry_suppressed_count",
            retry_suppressed_fallback,
        ),
        "initial_send_failed_count": _count(
            items, "event_engine_retry_initial_send_failed"
        ),
        "initial_send_error_count": _count(
            items, "event_engine_retry_initial_send_error"
        ),
        "limit_exceeded": bool(retry_limit_exceeded_meta),
        "limit_exceeded_count": _count(items, "event_engine_retry_limit_exceeded"),
        "max_inline_retries": _safe_int(
            retry_limit_exceeded_meta.get("max_inline_retries")
            or last_retry_meta.get("max_inline_retries")
            or final_state.get("max_inline_retries")
            or timeout_state.get("max_inline_retries"),
            0,
        ),
        "task_configured_count": _safe_int(
            _last_meta(items, "task_retry_config").get("retry_count"),
            0,
        ),
        "task_configured_total_attempts": _safe_int(
            _last_meta(items, "task_retry_config").get("total_attempts"),
            0,
        ),
        "task_last_event": last_task_retry_event,
        "task_scheduled_count": _count(items, "task_retry_scheduled"),
        "task_started_count": _count(items, "task_retry_started"),
        "task_last_attempt": _safe_int(last_task_retry_meta.get("attempt"), 0),
        "task_last_total_attempts": _safe_int(
            last_task_retry_meta.get("total_attempts"),
            0,
        ),
        "task_last_retry_count": _safe_int(
            last_task_retry_meta.get("retry_count"),
            0,
        ),
        "task_last_budget_remaining": _safe_int(
            last_task_retry_meta.get("retry_budget_remaining"),
            0,
        ),
        "task_last_error_type": str(last_task_retry_meta.get("error_type") or ""),
        "task_last_retryable": bool(last_task_retry_meta.get("retryable")),
    }


def _build_callbacks_summary(items, final_state, timeout_state) -> Dict[str, Any]:
    callback_confirmed_fallback = _count_callback_results(items, status="confirmed")
    callback_trusted_timeout_fallback = _count_callback_results(
        items, status="trusted_timeout"
    )
    callback_data_invalid_fallback = _count_callback_results(
        items, status="data_invalid_after_timeout"
    )
    callback_unconfirmed_fallback = _count_callback_results(items, confirmed=False)
    last_callback_meta = _last_callback_meta(items)
    callback_outer_timeout_fallback = _count(
        items, "event_engine_button_callback_outer_timeout"
    )
    last_callback_outer_timeout = _last_meta(
        items, "event_engine_button_callback_outer_timeout"
    )
    callback_exception_fallback = _count(
        items, "event_engine_button_callback_exception"
    )
    last_callback_exception = _last_meta(
        items, "event_engine_button_callback_exception"
    )
    last_callback_unconfirmed = _last_meta(
        items, "event_engine_button_callback_unconfirmed"
    )
    callback_released_fallback = _count(
        items, EVENT_ENGINE_BUTTON_CALLBACK_RELEASED_FOR_RETRY
    )
    last_callback_released = _last_meta(
        items, EVENT_ENGINE_BUTTON_CALLBACK_RELEASED_FOR_RETRY
    )
    stale_callback_text_fallback = max(
        _count(items, "event_engine_stale_callback_text_skipped"),
        _max_meta_int(
            items, "event_engine_stale_callback_text_skipped", "stale_callback_texts"
        ),
    )
    last_stale_callback_text = _last_meta(
        items,
        "event_engine_stale_callback_text_skipped",
    )
    return {
        "confirmed": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "callback_confirmed",
            callback_confirmed_fallback,
        ),
        "trusted_timeout": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "callback_trusted_timeout",
            callback_trusted_timeout_fallback,
        ),
        "data_invalid_after_timeout": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "callback_data_invalid_after_timeout",
            callback_data_invalid_fallback,
        ),
        "unconfirmed": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "callback_unconfirmed",
            callback_unconfirmed_fallback,
        ),
        "total_results": _count(items, "event_engine_button_callback_result"),
        "outer_timeouts": callback_outer_timeout_fallback,
        "exceptions": callback_exception_fallback,
        "released_for_retry": callback_released_fallback,
        "callback_texts": _count(items, "event_engine_callback_text_received"),
        "stale_callback_texts": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "stale_callback_texts",
            stale_callback_text_fallback,
        ),
        "last_status": str(last_callback_meta.get("callback_status") or ""),
        "last_reason": str(last_callback_meta.get("callback_reason") or ""),
        "last_source": str(last_callback_meta.get("source") or ""),
        "last_current_response_index": _safe_int(
            last_callback_meta.get("current_response_index"),
            0,
        ),
        "last_current_action": str(last_callback_meta.get("current_action") or ""),
        "last_retry_pending": bool(last_callback_meta.get("retry_pending")),
        "last_retry_budget_remaining": _safe_int(
            last_callback_meta.get("retry_budget_remaining"),
            0,
        ),
        "last_message_id": _safe_int(last_callback_meta.get("message_id"), 0),
        "last_button_text": str(last_callback_meta.get("button_text") or ""),
        "last_confirmed": bool(last_callback_meta.get("confirmed")),
        "last_attempt": _safe_int(last_callback_meta.get("callback_attempt"), 0),
        "last_max_retries": _safe_int(
            last_callback_meta.get("callback_max_retries"), 0
        ),
        "last_timeout": _safe_float(last_callback_meta.get("callback_timeout"), 0.0),
        "last_error_type": str(last_callback_meta.get("callback_error_type") or ""),
        "last_had_timeout": bool(last_callback_meta.get("callback_had_timeout")),
        "last_trusted_consumed": bool(last_callback_meta.get("trusted_consumed")),
        "last_has_callback_text": bool(last_callback_meta.get("has_callback_text")),
        "last_outer_timeout_source": str(
            last_callback_outer_timeout.get("source") or ""
        ),
        "last_outer_timeout_scope": str(
            last_callback_outer_timeout.get("timeout_scope") or ""
        ),
        "last_outer_operation_timeout": _safe_float(
            last_callback_outer_timeout.get("operation_timeout"),
            0.0,
        ),
        "last_outer_timeout_attempt_epoch": _safe_int(
            last_callback_outer_timeout.get("attempt_epoch"),
            0,
        ),
        "last_outer_timeout_current_response_index": _safe_int(
            last_callback_outer_timeout.get("current_response_index"),
            0,
        ),
        "last_outer_timeout_current_action": str(
            last_callback_outer_timeout.get("current_action") or ""
        ),
        "last_outer_timeout_retry_count": _safe_int(
            last_callback_outer_timeout.get("retry_count"),
            0,
        ),
        "last_outer_timeout_retry_budget_remaining": _safe_int(
            last_callback_outer_timeout.get("retry_budget_remaining"),
            0,
        ),
        "last_outer_timeout_retry_pending": bool(
            last_callback_outer_timeout.get("retry_pending")
        ),
        "last_exception_source": str(last_callback_exception.get("source") or ""),
        "last_exception_error_type": str(
            last_callback_exception.get("error_type") or ""
        ),
        "last_exception_operation_timeout": _safe_float(
            last_callback_exception.get("operation_timeout"),
            0.0,
        ),
        "last_unconfirmed_source": str(last_callback_unconfirmed.get("source") or ""),
        "last_unconfirmed_message_id": _safe_int(
            last_callback_unconfirmed.get("message_id"),
            0,
        ),
        "last_unconfirmed_button_text": str(
            last_callback_unconfirmed.get("button_text") or ""
        ),
        "last_unconfirmed_status": str(
            last_callback_unconfirmed.get("callback_status") or ""
        ),
        "last_unconfirmed_reason": str(
            last_callback_unconfirmed.get("callback_reason") or ""
        ),
        "last_unconfirmed_attempt_epoch": _safe_int(
            last_callback_unconfirmed.get("attempt_epoch"),
            0,
        ),
        "last_unconfirmed_current_response_index": _safe_int(
            last_callback_unconfirmed.get("current_response_index"),
            0,
        ),
        "last_unconfirmed_current_action": str(
            last_callback_unconfirmed.get("current_action") or ""
        ),
        "last_unconfirmed_retry_count": _safe_int(
            last_callback_unconfirmed.get("retry_count"),
            0,
        ),
        "last_unconfirmed_retry_budget_remaining": _safe_int(
            last_callback_unconfirmed.get("retry_budget_remaining"),
            0,
        ),
        "last_unconfirmed_retry_pending": bool(
            last_callback_unconfirmed.get("retry_pending")
        ),
        "last_unconfirmed_attempt": _safe_int(
            last_callback_unconfirmed.get("callback_attempt"),
            0,
        ),
        "last_unconfirmed_max_retries": _safe_int(
            last_callback_unconfirmed.get("callback_max_retries"),
            0,
        ),
        "last_unconfirmed_timeout": _safe_float(
            last_callback_unconfirmed.get("callback_timeout"),
            0.0,
        ),
        "last_unconfirmed_error_type": str(
            last_callback_unconfirmed.get("callback_error_type") or ""
        ),
        "last_unconfirmed_had_timeout": bool(
            last_callback_unconfirmed.get("callback_had_timeout")
        ),
        "last_released_source": str(last_callback_released.get("source") or ""),
        "last_released_message_id": _safe_int(
            last_callback_released.get("message_id"),
            0,
        ),
        "last_released_button_text": str(
            last_callback_released.get("button_text") or ""
        ),
        "last_released_status": str(
            last_callback_released.get("callback_status") or ""
        ),
        "last_released_attempt_epoch": _safe_int(
            last_callback_released.get("attempt_epoch"),
            0,
        ),
        "last_released_current_response_index": _safe_int(
            last_callback_released.get("current_response_index"),
            0,
        ),
        "last_released_current_action": str(
            last_callback_released.get("current_action") or ""
        ),
        "last_released_retry_count": _safe_int(
            last_callback_released.get("retry_count"),
            0,
        ),
        "last_released_retry_budget_remaining": _safe_int(
            last_callback_released.get("retry_budget_remaining"),
            0,
        ),
        "last_released_attempt": _safe_int(
            last_callback_released.get("callback_attempt"),
            0,
        ),
        "last_released_max_retries": _safe_int(
            last_callback_released.get("callback_max_retries"),
            0,
        ),
        "last_released_timeout": _safe_float(
            last_callback_released.get("callback_timeout"),
            0.0,
        ),
        "last_released_retry_pending": bool(
            last_callback_released.get("retry_pending")
        ),
        "last_released_clicked_versions": _safe_int(
            last_callback_released.get("clicked_versions"),
            0,
        ),
        "last_stale_callback_text_message_id": _safe_int(
            last_stale_callback_text.get("message_id"),
            0,
        ),
        "last_stale_callback_text_attempt_epoch": _safe_int(
            last_stale_callback_text.get("callback_attempt_epoch"),
            0,
        ),
        "last_stale_callback_text_current_epoch": _safe_int(
            last_stale_callback_text.get("current_attempt_epoch"),
            0,
        ),
    }


def _build_messages_summary(items, final_state, timeout_state) -> Dict[str, Any]:
    last_response_action_advanced = _last_meta(
        items, "event_engine_response_action_advanced"
    )
    last_response_action_not_advanced = _last_meta(
        items, "event_engine_response_action_not_advanced"
    )
    last_message_retryable_error = _last_meta(
        items, "event_engine_message_retryable_error"
    )
    skipped_duplicate_fallback = max(
        _count_message_skips(items, "duplicate"),
        _max_meta_int(items, "event_engine_message_skip_recorded", "skipped_duplicate"),
    )
    skipped_concurrent_duplicate_fallback = max(
        _count_message_skips(items, "concurrent_duplicate"),
        _max_meta_int(
            items, "event_engine_message_skip_recorded", "skipped_concurrent_duplicate"
        ),
    )
    skipped_finished_fallback = max(
        _count_message_skips(items, "finished"),
        _max_meta_int(items, "event_engine_message_skip_recorded", "skipped_finished"),
    )
    skipped_non_inbound_fallback = max(
        _count_message_skips(items, "non_inbound"),
        _max_meta_int(
            items, "event_engine_message_skip_recorded", "skipped_non_inbound"
        ),
    )
    last_message_skip = _last_meta(items, "event_engine_message_skip_recorded")
    last_stale_attempt_mark = _last_meta(
        items,
        "event_engine_stale_attempt_processed_mark_skipped",
    )
    message_processing_cancelled_fallback = max(
        _count(items, EVENT_ENGINE_MESSAGE_PROCESSING_CANCELLED),
        _max_meta_int(
            items,
            EVENT_ENGINE_MESSAGE_PROCESSING_CANCELLED,
            "message_processing_cancelled",
        ),
    )
    last_message_processing_cancelled = _last_meta(
        items,
        EVENT_ENGINE_MESSAGE_PROCESSING_CANCELLED,
    )
    return {
        "processed_versions": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "processed_versions",
            0,
        ),
        "processing_versions": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "processing_versions",
            0,
        ),
        "sent_captcha_versions": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "sent_captcha_versions",
            0,
        ),
        "captcha_result_text_preemptions": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "captcha_result_text_preemptions",
            _count(items, EVENT_ENGINE_CAPTCHA_RESULT_TEXT_PREEMPTED),
        ),
        "response_messages_sent": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "response_messages_sent",
            _max_meta_int(
                items, "event_engine_response_message_sent", "response_messages_sent"
            )
            or _count(items, "event_engine_response_message_sent"),
        ),
        "response_actions_advanced": _count(
            items,
            "event_engine_response_action_advanced",
        ),
        "last_response_action_from_index": _safe_int(
            last_response_action_advanced.get("from_index"),
            0,
        ),
        "last_response_action_to_index": _safe_int(
            last_response_action_advanced.get("to_index"),
            0,
        ),
        "last_response_action_source": str(
            last_response_action_advanced.get("source") or ""
        ),
        "last_response_action_reason": str(
            last_response_action_advanced.get("reason") or ""
        ),
        "last_response_action_attempt_epoch": _safe_int(
            last_response_action_advanced.get("attempt_epoch"),
            0,
        ),
        "last_response_action_message_id": _safe_int(
            last_response_action_advanced.get("message_id"),
            0,
        ),
        "response_actions_not_advanced": _count(
            items,
            "event_engine_response_action_not_advanced",
        ),
        "last_response_action_not_advanced_index": _safe_int(
            last_response_action_not_advanced.get("current_response_index"),
            0,
        ),
        "last_response_action_not_advanced_source": str(
            last_response_action_not_advanced.get("source") or ""
        ),
        "last_response_action_not_advanced_reason": str(
            last_response_action_not_advanced.get("reason") or ""
        ),
        "last_response_action_not_advanced_finished": bool(
            last_response_action_not_advanced.get("finished")
        ),
        "last_response_action_not_advanced_retry_pending": bool(
            last_response_action_not_advanced.get("retry_pending")
        ),
        "last_response_action_not_advanced_attempt_epoch": _safe_int(
            last_response_action_not_advanced.get("attempt_epoch"),
            0,
        ),
        "last_response_action_not_advanced_message_id": _safe_int(
            last_response_action_not_advanced.get("message_id"),
            0,
        ),
        "message_retryable_errors": _count(
            items,
            "event_engine_message_retryable_error",
        ),
        "last_message_retryable_message_id": _safe_int(
            last_message_retryable_error.get("message_id"),
            0,
        ),
        "last_message_retryable_error_type": str(
            last_message_retryable_error.get("error_type") or ""
        ),
        "last_message_retryable_operation": str(
            last_message_retryable_error.get("operation") or ""
        ),
        "last_message_retryable_timeout_scope": str(
            last_message_retryable_error.get("timeout_scope") or ""
        ),
        "last_message_retryable_operation_timeout": _safe_float(
            last_message_retryable_error.get("operation_timeout"),
            0.0,
        ),
        "last_message_retryable_attempt_epoch": _safe_int(
            last_message_retryable_error.get("attempt_epoch"),
            0,
        ),
        "last_message_retryable_current_response_index": _safe_int(
            last_message_retryable_error.get("current_response_index"),
            0,
        ),
        "last_message_retryable_current_action": str(
            last_message_retryable_error.get("current_action") or ""
        ),
        "last_message_retryable_retry_count": _safe_int(
            last_message_retryable_error.get("retry_count"),
            0,
        ),
        "last_message_retryable_retry_budget_remaining": _safe_int(
            last_message_retryable_error.get("retry_budget_remaining"),
            0,
        ),
        "last_message_retryable_retry_pending": bool(
            last_message_retryable_error.get("retry_pending")
        ),
        "clicked_versions": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "clicked_versions",
            0,
        ),
        "skipped_clicked_duplicate": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "skipped_clicked_duplicate",
            _max_meta_int(
                items,
                "event_engine_button_click_duplicate_skipped",
                "clicked_duplicate",
            ),
        ),
        "skipped_duplicate": max(
            _snapshot_int_or_event_count(
                final_state,
                timeout_state,
                "skipped_duplicate",
                skipped_duplicate_fallback,
            ),
            skipped_duplicate_fallback,
        ),
        "skipped_concurrent_duplicate": max(
            _snapshot_int_or_event_count(
                final_state,
                timeout_state,
                "skipped_concurrent_duplicate",
                skipped_concurrent_duplicate_fallback,
            ),
            skipped_concurrent_duplicate_fallback,
        ),
        "skipped_finished": max(
            _snapshot_int_or_event_count(
                final_state,
                timeout_state,
                "skipped_finished",
                skipped_finished_fallback,
            ),
            skipped_finished_fallback,
        ),
        "skipped_non_inbound": max(
            _snapshot_int_or_event_count(
                final_state,
                timeout_state,
                "skipped_non_inbound",
                skipped_non_inbound_fallback,
            ),
            skipped_non_inbound_fallback,
        ),
        "message_processing_cancelled": max(
            _snapshot_int_or_event_count(
                final_state,
                timeout_state,
                "message_processing_cancelled",
                message_processing_cancelled_fallback,
            ),
            message_processing_cancelled_fallback,
        ),
        "last_message_processing_cancelled_message_id": _safe_int(
            last_message_processing_cancelled.get("message_id"),
            0,
        ),
        "last_message_processing_cancelled_version_hash": str(
            last_message_processing_cancelled.get("message_version_hash") or ""
        ),
        "last_message_processing_cancelled_action": str(
            last_message_processing_cancelled.get("current_action") or ""
        ),
        "last_message_processing_cancelled_attempt_epoch": _safe_int(
            last_message_processing_cancelled.get("attempt_epoch"),
            0,
        ),
        "last_message_processing_cancelled_retry_pending": bool(
            last_message_processing_cancelled.get("retry_pending")
        ),
        "last_message_processing_cancelled_will_release": bool(
            last_message_processing_cancelled.get("will_release_processing_version")
        ),
        "stale_attempt_processed_marks": _count(
            items,
            "event_engine_stale_attempt_processed_mark_skipped",
        ),
        "last_stale_attempt_message_epoch": _safe_int(
            last_stale_attempt_mark.get("message_attempt_epoch"),
            0,
        ),
        "last_stale_attempt_current_epoch": _safe_int(
            last_stale_attempt_mark.get("current_attempt_epoch"),
            0,
        ),
        "last_skip_reason": str(last_message_skip.get("reason") or ""),
        "last_skip_message_id": _safe_int(
            last_message_skip.get("message_id"),
            0,
        ),
        "last_skip_message_version_hash": str(
            last_message_skip.get("message_version_hash") or ""
        ),
        "last_skip_attempt_epoch": _safe_int(
            last_message_skip.get("attempt_epoch"),
            0,
        ),
        "last_skip_current_response_index": _safe_int(
            last_message_skip.get("current_response_index"),
            0,
        ),
        "last_skip_current_action": str(last_message_skip.get("current_action") or ""),
        "last_skip_retry_count": _safe_int(
            last_message_skip.get("retry_count"),
            0,
        ),
        "last_skip_retry_budget_remaining": _safe_int(
            last_message_skip.get("retry_budget_remaining"),
            0,
        ),
        "last_skip_retry_pending": bool(last_message_skip.get("retry_pending")),
        "unhandled": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "unhandled_messages",
            _max_meta_int(
                items, "event_engine_message_unhandled", "unhandled_messages"
            ),
        ),
    }


def _build_history_summary(items, final_state, timeout_state) -> Dict[str, Any]:
    latest_history_failed = _last_meta(items, "event_engine_history_failed")
    latest_history_scan = _last_history_scan_meta(items)
    history_startup_scans_fallback = sum(
        1
        for item in items
        if _event(item) == "event_engine_history_scan_completed"
        and _meta(item).get("source") == "startup"
    )
    history_rescue_scans_fallback = _count(items, "event_engine_history_rescue_started")
    history_failed_scans_fallback = _count(items, "event_engine_history_failed")
    history_messages_handled_fallback = _sum_meta_int(
        items,
        "event_engine_history_scan_completed",
        "handled_count",
    )
    history_duplicate_messages_fallback = max(
        _count(items, "event_engine_history_duplicate_skipped"),
        _max_meta_int(
            items, "event_engine_history_duplicate_skipped", "duplicate_count"
        ),
    )
    history_messages_seen_fallback = _sum_meta_int(
        items,
        "event_engine_history_scan_completed",
        "message_count",
    )
    history_messages_allowed_fallback = _sum_meta_int(
        items,
        "event_engine_history_scan_completed",
        "allowed_count",
    )
    history_tracked_rechecks_fallback = _count(
        items, "event_engine_history_tracked_message_rechecked"
    )
    history_concurrent_skipped_fallback = _count(
        items, "event_engine_history_scan_concurrent_skipped"
    )
    history_cancelled_scans_fallback = max(
        _count(items, "event_engine_history_rescue_cancelled"),
        _count(items, "event_engine_history_scan_cancelled"),
        _max_meta_int(
            items,
            "event_engine_history_scan_cancelled",
            "cancelled_scans",
        ),
    )
    history_expired_fallback = _count(items, "event_engine_history_message_expired")
    history_filtered_before_entry_fallback = max(
        sum(
            1
            for item in items
            if _event(item) == "event_engine_history_message_filtered"
            and str(_meta(item).get("reason") or "") == "before_entry_untracked"
        ),
        _max_meta_int(
            items, "event_engine_history_message_filtered", "filtered_before_entry"
        ),
    )
    history_filtered_expired_fallback = max(
        sum(
            1
            for item in items
            if _event(item) == "event_engine_history_message_filtered"
            and str(_meta(item).get("reason") or "") == "expired"
        ),
        _max_meta_int(
            items, "event_engine_history_message_filtered", "filtered_expired"
        ),
    )
    history_hard_failures_skipped_fallback = max(
        _count(items, "event_engine_history_hard_failure_skipped"),
        _max_meta_int(
            items,
            "event_engine_history_hard_failure_skipped",
            "hard_failures_skipped",
        ),
    )
    history_unhandled_duplicates_fallback = max(
        _count(items, "event_engine_history_unhandled_duplicate_skipped"),
        _max_meta_int(
            items,
            "event_engine_history_unhandled_duplicate_skipped",
            "unhandled_duplicate_count",
        ),
    )
    history_circuit_opened_fallback = _count(
        items, "event_engine_history_rescue_suspended"
    )
    latest_history_suspended = _last_meta(
        items, "event_engine_history_rescue_suspended"
    )
    return {
        "startup_scans": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "history_startup_scans",
            history_startup_scans_fallback,
        ),
        "rescue_scans": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "history_rescue_scans",
            history_rescue_scans_fallback,
        ),
        "failed_scans": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "history_failed_scans",
            history_failed_scans_fallback,
        ),
        "messages_handled": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "history_messages_handled",
            history_messages_handled_fallback,
        ),
        "duplicate_messages": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "history_duplicate_messages",
            history_duplicate_messages_fallback,
        ),
        "messages_seen": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "history_messages_seen",
            history_messages_seen_fallback,
        ),
        "messages_allowed": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "history_messages_allowed",
            history_messages_allowed_fallback,
        ),
        "tracked_rechecks": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "history_tracked_rechecks",
            history_tracked_rechecks_fallback,
        ),
        "concurrent_skipped": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "history_concurrent_skipped",
            history_concurrent_skipped_fallback,
        ),
        "cancelled_scans": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "history_cancelled_scans",
            history_cancelled_scans_fallback,
        ),
        "scan_in_progress": _snapshot_bool_or_event_flag(
            final_state,
            timeout_state,
            "history_scan_in_progress",
            bool(history_concurrent_skipped_fallback),
        ),
        "rescue_suspended": _snapshot_bool_or_event_flag(
            final_state,
            timeout_state,
            "history_rescue_suspended",
            bool(_count(items, "event_engine_history_rescue_suspended")),
        ),
        "circuit_opened": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "history_circuit_opened",
            history_circuit_opened_fallback,
        ),
        "consecutive_failures": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "history_consecutive_failures",
            _last_int_from_event(
                items,
                "event_engine_history_failed",
                "consecutive_failures",
            ),
        ),
        "expired_messages": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "history_expired_messages",
            history_expired_fallback,
        ),
        "filtered_before_entry": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "history_filtered_before_entry",
            history_filtered_before_entry_fallback,
        ),
        "filtered_expired": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "history_filtered_expired",
            history_filtered_expired_fallback,
        ),
        "hard_failures_skipped": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "history_hard_failures_skipped",
            history_hard_failures_skipped_fallback,
        ),
        "unhandled_duplicates": _snapshot_int_or_event_count(
            final_state,
            timeout_state,
            "history_unhandled_duplicates",
            history_unhandled_duplicates_fallback,
        ),
        "last_scan_status": _snapshot_value(
            final_state,
            timeout_state,
            "last_history_scan_status",
            latest_history_scan.get("status") or "",
        ),
        "last_scan_source": _snapshot_value(
            final_state,
            timeout_state,
            "last_history_scan_source",
            latest_history_scan.get("source") or "",
        ),
        "last_scan_message_count": _safe_int(
            _snapshot_value(
                final_state,
                timeout_state,
                "last_history_scan_message_count",
                latest_history_scan.get("message_count") or 0,
            ),
            0,
        ),
        "last_scan_allowed_count": _safe_int(
            _snapshot_value(
                final_state,
                timeout_state,
                "last_history_scan_allowed_count",
                latest_history_scan.get("allowed_count") or 0,
            ),
            0,
        ),
        "last_scan_handled_count": _safe_int(
            _snapshot_value(
                final_state,
                timeout_state,
                "last_history_scan_handled_count",
                latest_history_scan.get("handled_count") or 0,
            ),
            0,
        ),
        "last_scan_error_type": str(
            _snapshot_value(
                final_state,
                timeout_state,
                "last_history_scan_error_type",
                latest_history_scan.get("error_type") or "",
            )
            or ""
        ),
        "last_scan_attempt_epoch": _safe_int(
            _snapshot_value(
                final_state,
                timeout_state,
                "last_history_scan_attempt_epoch",
                latest_history_scan.get("attempt_epoch"),
            ),
            0,
        ),
        "last_scan_current_response_index": _safe_int(
            _snapshot_value(
                final_state,
                timeout_state,
                "last_history_scan_current_response_index",
                latest_history_scan.get("current_response_index"),
            ),
            0,
        ),
        "last_scan_current_action": str(
            _snapshot_value(
                final_state,
                timeout_state,
                "last_history_scan_current_action",
                latest_history_scan.get("current_action") or "",
            )
            or ""
        ),
        "last_scan_retry_count": _safe_int(
            _snapshot_value(
                final_state,
                timeout_state,
                "last_history_scan_retry_count",
                latest_history_scan.get("retry_count"),
            ),
            0,
        ),
        "last_scan_retry_budget_remaining": _safe_int(
            _snapshot_value(
                final_state,
                timeout_state,
                "last_history_scan_retry_budget_remaining",
                latest_history_scan.get("retry_budget_remaining"),
            ),
            0,
        ),
        "last_scan_retry_pending": bool(
            _snapshot_value(
                final_state,
                timeout_state,
                "last_history_scan_retry_pending",
                latest_history_scan.get("retry_pending"),
            )
        ),
        "last_failed_source": latest_history_failed.get("source")
        or _snapshot_value(final_state, timeout_state, "last_history_scan_source", ""),
        "last_failed_operation": latest_history_failed.get("operation") or "",
        "last_failed_timeout_scope": latest_history_failed.get("timeout_scope") or "",
        "last_failed_error_type": latest_history_failed.get("error_type")
        or _snapshot_value(
            final_state, timeout_state, "last_history_scan_error_type", ""
        ),
        "last_failed_timeout": _safe_float(
            latest_history_failed.get("operation_timeout")
            or latest_history_failed.get("timeout"),
            0.0,
        ),
        "last_failed_scan_count": _safe_int(
            latest_history_failed.get("failed_scans"),
            0,
        ),
        "last_failure_scan_in_progress": bool(
            latest_history_failed.get("scan_in_progress")
        ),
        "last_failure_blocks_main_flow": bool(
            latest_history_failed.get("blocks_main_flow")
        ),
        "last_failure_retry_pending": bool(latest_history_failed.get("retry_pending")),
        "last_failure_will_open_circuit": bool(
            latest_history_failed.get("will_open_circuit")
        ),
        "last_failure_rescue_will_continue": bool(
            latest_history_failed.get("rescue_will_continue")
        ),
        "last_suspended_source": str(latest_history_suspended.get("source") or ""),
        "last_suspended_status": str(latest_history_suspended.get("status") or ""),
        "last_suspended_attempt_epoch": _safe_int(
            latest_history_suspended.get("attempt_epoch"),
            0,
        ),
        "last_suspended_current_response_index": _safe_int(
            latest_history_suspended.get("current_response_index"),
            0,
        ),
        "last_suspended_current_action": str(
            latest_history_suspended.get("current_action") or ""
        ),
        "last_suspended_retry_count": _safe_int(
            latest_history_suspended.get("retry_count"),
            0,
        ),
        "last_suspended_retry_budget_remaining": _safe_int(
            latest_history_suspended.get("retry_budget_remaining"),
            0,
        ),
        "last_suspended_retry_pending": bool(
            latest_history_suspended.get("retry_pending")
        ),
    }


def _build_timeouts_summary(items) -> Dict[str, Any]:
    task_run_timeout = _last_meta(items, "task_run_timeout")
    callback_outer_timeout_fallback = _count(
        items, "event_engine_button_callback_outer_timeout"
    )
    last_rpc_timeout_event, last_rpc_timeout_kind, last_rpc_timeout = (
        _last_rpc_timeout_meta(items)
    )
    last_client_startup_retry = _last_meta(items, "client_startup_retry_scheduled")
    last_client_rpc_late_event, last_client_rpc_late = _last_client_rpc_late_meta(items)
    client_cleanup_rpc_timeouts = _count_client_cleanup_rpc_timeouts(items)
    last_client_cleanup_rpc_timeout = _last_client_cleanup_rpc_timeout_meta(items)
    last_late_timeout_event, last_late_timeout = _last_hard_timeout_late_meta(items)
    last_task_run_late_event, last_task_run_late = _last_task_run_late_meta(items)
    return {
        "timeout_count_total": _timeout_count_total(
            items,
            client_cleanup_rpc_timeouts=client_cleanup_rpc_timeouts,
        ),
        "event": _count(items, "event_engine_timeout_state"),
        "response_action": _count(items, "event_engine_response_action_timeout"),
        "callback_outer": callback_outer_timeout_fallback,
        "send_rpc": _count(items, "event_engine_initial_send_retryable_error")
        + _count(items, "event_engine_followup_send_retryable_error")
        + _count(items, "event_engine_response_send_retryable_error"),
        "media_rpc": _count(items, "event_engine_media_download_retryable_error"),
        "ai_rpc": _count(items, "event_engine_ai_retryable_error"),
        "task_run": _count(items, "task_run_timeout"),
        "client_rpc": _count(items, "client_rpc_hard_timeout"),
        "client_cleanup_rpc": client_cleanup_rpc_timeouts,
        "client_cleanup_rpc_last_timeout": _safe_float(
            last_client_cleanup_rpc_timeout.get("timeout"),
            0.0,
        ),
        "client_rpc_late_cancelled": _count(items, "client_rpc_late_cancelled"),
        "client_rpc_late_completed": _count(items, "client_rpc_late_completed"),
        "client_rpc_late_exception": _count(items, "client_rpc_late_exception"),
        "client_rpc_last_late_event": last_client_rpc_late_event,
        "client_rpc_last_late_operation": str(
            last_client_rpc_late.get("operation") or ""
        ),
        "client_rpc_last_late_timeout_scope": str(
            last_client_rpc_late.get("timeout_scope") or ""
        ),
        "client_rpc_last_late_error_type": str(
            last_client_rpc_late.get("error_type") or ""
        ),
        "client_rpc_last_late_timeout": _safe_float(
            last_client_rpc_late.get("timeout"),
            0.0,
        ),
        "client_startup_retry": _count(items, "client_startup_retry_scheduled"),
        "client_startup_retry_last_attempt": _safe_int(
            last_client_startup_retry.get("attempt"),
            0,
        ),
        "client_startup_retry_total_attempts": _safe_int(
            last_client_startup_retry.get("total_attempts"),
            0,
        ),
        "client_startup_retry_budget_remaining": _safe_int(
            last_client_startup_retry.get("retry_budget_remaining"),
            0,
        ),
        "client_startup_retry_wait_seconds": _safe_float(
            last_client_startup_retry.get("wait_seconds"),
            0.0,
        ),
        "client_startup_retry_cleanup_attempted": bool(
            last_client_startup_retry.get("cleanup_attempted")
        ),
        "client_startup_retry_error_type": str(
            last_client_startup_retry.get("error_type") or ""
        ),
        "client_startup_retry_reason": str(
            last_client_startup_retry.get("reason") or ""
        ),
        "client_startup_lock": _count(items, "client_startup_lock_timeout"),
        "client_startup_lock_timeout_seconds": _safe_float(
            _last_meta(items, "client_startup_lock_timeout").get("timeout_seconds"),
            0.0,
        ),
        "client_exit_lock": _count(items, "client_exit_lock_timeout"),
        "client_exit_lock_timeout_seconds": _safe_float(
            _last_meta(items, "client_exit_lock_timeout").get("timeout_seconds"),
            0.0,
        ),
        "client_close_lock": _count(items, "client_close_lock_timeout"),
        "client_close_lock_timeout_seconds": _safe_float(
            _last_meta(items, "client_close_lock_timeout").get("timeout_seconds"),
            0.0,
        ),
        "task_run_late_cancelled": _count(items, "task_run_late_cancelled"),
        "task_run_late_completed": _count(items, "task_run_late_completed"),
        "task_run_late_exception": _count(items, "task_run_late_exception"),
        "task_run_last_late_event": last_task_run_late_event,
        "task_run_last_late_operation": str(last_task_run_late.get("operation") or ""),
        "task_run_last_late_timeout_scope": str(
            last_task_run_late.get("timeout_scope") or ""
        ),
        "task_run_last_late_error_type": str(
            last_task_run_late.get("error_type") or ""
        ),
        "task_run_last_late_timeout_seconds": _safe_float(
            last_task_run_late.get("timeout_seconds"),
            0.0,
        ),
        "task_run_last_late_attempt": _safe_int(last_task_run_late.get("attempt"), 0),
        "task_run_last_late_total_attempts": _safe_int(
            last_task_run_late.get("total_attempts"),
            0,
        ),
        "task_run_cancelled": bool(task_run_timeout.get("run_task_cancelled")),
        "task_run_cleanup_expected": bool(task_run_timeout.get("cleanup_expected")),
        "task_run_operation": str(task_run_timeout.get("operation") or ""),
        "task_run_timeout_scope": str(task_run_timeout.get("timeout_scope") or ""),
        "task_run_timeout_seconds": _safe_float(
            task_run_timeout.get("timeout_seconds"),
            0.0,
        ),
        "task_run_attempt": _safe_int(task_run_timeout.get("attempt"), 0),
        "task_run_total_attempts": _safe_int(
            task_run_timeout.get("total_attempts"),
            0,
        ),
        "late_cancelled": _count(items, EVENT_ENGINE_HARD_TIMEOUT_LATE_CANCELLED),
        "late_completed": _count(items, EVENT_ENGINE_HARD_TIMEOUT_LATE_COMPLETED),
        "late_exception": _count(items, EVENT_ENGINE_HARD_TIMEOUT_LATE_EXCEPTION),
        "last_late_event": last_late_timeout_event,
        "last_late_operation": str(last_late_timeout.get("operation") or ""),
        "last_late_timeout_scope": str(last_late_timeout.get("timeout_scope") or ""),
        "last_late_source": str(last_late_timeout.get("source") or ""),
        "last_late_message_id": _safe_int(last_late_timeout.get("message_id"), 0),
        "last_late_error_type": str(last_late_timeout.get("error_type") or ""),
        "last_late_timeout": _safe_float(last_late_timeout.get("timeout"), 0.0),
        "last_late_cancelled_by_parent": bool(
            last_late_timeout.get("cancelled_by_parent")
        ),
        "last_late_attempt_epoch": _safe_int(
            last_late_timeout.get("attempt_epoch"),
            0,
        ),
        "last_late_current_response_index": _safe_int(
            last_late_timeout.get("current_response_index"),
            0,
        ),
        "last_late_current_action": str(last_late_timeout.get("current_action") or ""),
        "last_late_retry_count": _safe_int(
            last_late_timeout.get("retry_count"),
            0,
        ),
        "last_late_retry_budget_remaining": _safe_int(
            last_late_timeout.get("retry_budget_remaining"),
            0,
        ),
        "last_late_retry_pending": bool(last_late_timeout.get("retry_pending")),
        "last_rpc_event": last_rpc_timeout_event,
        "last_rpc_kind": last_rpc_timeout_kind,
        "last_rpc_operation": str(last_rpc_timeout.get("operation") or ""),
        "last_rpc_timeout_scope": str(last_rpc_timeout.get("timeout_scope") or ""),
        "last_rpc_source": str(last_rpc_timeout.get("source") or ""),
        "last_rpc_message_id": _safe_int(
            last_rpc_timeout.get("message_id"),
            0,
        ),
        "last_rpc_source_message_id": _safe_int(
            last_rpc_timeout.get("source_message_id"),
            0,
        ),
        "last_rpc_error_type": str(last_rpc_timeout.get("error_type") or ""),
        "last_rpc_timeout": _safe_float(
            last_rpc_timeout.get("operation_timeout")
            or last_rpc_timeout.get("timeout")
            or last_rpc_timeout.get("timeout_seconds"),
            0.0,
        ),
    }


def _build_runtime_summary(items, final_state, timeout_state) -> Dict[str, Any]:
    worker_contract = _last_meta(items, "worker_execution_contract")
    return {
        **_runtime_budget_summary(final_state, timeout_state, worker_contract),
        **_runtime_boolean_count_summary(worker_contract),
        **_runtime_shape_summary(worker_contract),
        "runtime_config_key": _runtime_value(
            final_state,
            timeout_state,
            worker_contract,
            "runtime_config_key",
        ),
        "ai_fallback_enabled": _runtime_value(
            final_state,
            timeout_state,
            worker_contract,
            "ai_fallback_enabled",
        ),
    }


def _build_cleanup_summary(items) -> Dict[str, Any]:
    cleanup_completed = _last_meta(items, "client_cleanup_completed")
    cleanup_failed = _last_meta(items, "client_cleanup_failed")
    cleanup_started = _last_meta(items, "client_cleanup_started")
    cleanup_deferred_cancel = _last_meta(
        items, "task_cancellation_deferred_for_cleanup"
    )
    cleanup_late_event, cleanup_late_meta = _last_client_cleanup_late_meta(items)
    cleanup_last_event, cleanup_last_meta = _last_event_meta(
        items,
        {
            "client_cleanup_started",
            "client_cleanup_completed",
            "client_cleanup_failed",
        },
    )
    client_cleanup_rpc_timeouts = _count_client_cleanup_rpc_timeouts(items)
    last_client_cleanup_rpc_timeout = _last_client_cleanup_rpc_timeout_meta(items)
    last_client_cleanup_rpc_late_event, last_client_cleanup_rpc_late = (
        _last_client_cleanup_rpc_late_meta(items)
    )
    return {
        "started": bool(_count(items, "client_cleanup_started")),
        "completed": bool(cleanup_completed),
        "failed": bool(cleanup_failed),
        "last_event": cleanup_last_event,
        "last_attempt": _safe_int(cleanup_last_meta.get("attempt"), 0),
        "last_total_attempts": _safe_int(cleanup_last_meta.get("total_attempts"), 0),
        "last_success": bool(cleanup_last_meta.get("success")),
        "last_operation": str(cleanup_last_meta.get("operation") or ""),
        "last_timeout_scope": str(cleanup_last_meta.get("timeout_scope") or ""),
        "error_type": cleanup_failed.get("error_type"),
        "timeout_seconds": _safe_float(
            cleanup_failed.get("timeout_seconds")
            or cleanup_completed.get("timeout_seconds")
            or cleanup_started.get("timeout_seconds"),
            0.0,
        ),
        "manager_lock_present": bool(cleanup_completed.get("lock_present")),
        "manager_lock_acquired": bool(cleanup_completed.get("lock_acquired")),
        "manager_lock_wait_timeout": bool(cleanup_completed.get("lock_wait_timeout")),
        "manager_lock_timeout_seconds": _safe_float(
            cleanup_completed.get("lock_timeout_seconds"),
            0.0,
        ),
        "manager_force_cleanup": bool(cleanup_completed.get("force_cleanup")),
        "manager_client_found": bool(cleanup_completed.get("client_found")),
        "manager_cleanup_attempted": bool(cleanup_completed.get("cleanup_attempted")),
        "manager_cleanup_error_type": str(
            cleanup_completed.get("cleanup_error_type") or ""
        ),
        "rpc_attempts": _safe_int(
            cleanup_completed.get("cleanup_step_attempts"),
            0,
        ),
        "rpc_timeouts": max(
            client_cleanup_rpc_timeouts,
            _safe_int(cleanup_completed.get("cleanup_step_timeouts"), 0),
        ),
        "rpc_errors": _safe_int(
            cleanup_completed.get("cleanup_step_errors"),
            0,
        ),
        "last_rpc_error_type": str(
            cleanup_completed.get("cleanup_step_last_error_type") or ""
        ),
        "last_rpc_timeout": _safe_float(
            last_client_cleanup_rpc_timeout.get("timeout"),
            _safe_float(cleanup_completed.get("cleanup_step_last_timeout"), 0.0),
        ),
        "rpc_late_cancelled": _count_client_cleanup_rpc_late(
            items,
            "client_rpc_late_cancelled",
        ),
        "rpc_late_completed": _count_client_cleanup_rpc_late(
            items,
            "client_rpc_late_completed",
        ),
        "rpc_late_exception": _count_client_cleanup_rpc_late(
            items,
            "client_rpc_late_exception",
        ),
        "last_rpc_late_event": last_client_cleanup_rpc_late_event,
        "last_rpc_late_error_type": str(
            last_client_cleanup_rpc_late.get("error_type") or ""
        ),
        "last_rpc_late_timeout": _safe_float(
            last_client_cleanup_rpc_late.get("timeout"),
            0.0,
        ),
        "deferred_cancellations": _count(
            items, "task_cancellation_deferred_for_cleanup"
        ),
        "last_deferred_cancel_attempt": _safe_int(
            cleanup_deferred_cancel.get("attempt"),
            0,
        ),
        "last_deferred_cancel_total_attempts": _safe_int(
            cleanup_deferred_cancel.get("total_attempts"),
            0,
        ),
        "last_deferred_cancel_success": bool(cleanup_deferred_cancel.get("success")),
        "last_deferred_cancel_timeout_seconds": _safe_float(
            cleanup_deferred_cancel.get("timeout_seconds"),
            0.0,
        ),
        "late_cancelled": _count(items, "client_cleanup_late_cancelled"),
        "late_completed": _count(items, "client_cleanup_late_completed"),
        "late_exception": _count(items, "client_cleanup_late_exception"),
        "last_late_event": cleanup_late_event,
        "last_late_operation": str(cleanup_late_meta.get("operation") or ""),
        "last_late_timeout_scope": str(cleanup_late_meta.get("timeout_scope") or ""),
        "last_late_error_type": str(cleanup_late_meta.get("error_type") or ""),
        "last_late_timeout_seconds": _safe_float(
            cleanup_late_meta.get("timeout_seconds"),
            0.0,
        ),
        "last_late_attempt": _safe_int(cleanup_late_meta.get("attempt"), 0),
        "last_late_total_attempts": _safe_int(
            cleanup_late_meta.get("total_attempts"),
            0,
        ),
        "last_late_success": bool(cleanup_late_meta.get("success")),
    }


def _build_gate_summary(items, prefix: str) -> Dict[str, Any]:
    acquired = _last_meta(items, f"{prefix}_acquired")
    timed_out = _last_meta(items, f"{prefix}_wait_timeout")
    released = _last_meta(items, f"{prefix}_released")
    latest = (
        released or acquired or timed_out or _last_meta(items, f"{prefix}_wait_started")
    )
    return {
        "waited": _has_event(items, f"{prefix}_wait_started"),
        "acquired": _has_event(items, f"{prefix}_acquired"),
        "wait_timeout": bool(timed_out),
        "last_operation": str(latest.get("operation") or ""),
        "last_timeout_scope": str(latest.get("timeout_scope") or ""),
        "wait_timeout_seconds": _safe_float(timed_out.get("timeout_seconds"), 0.0),
        "released": _has_event(items, f"{prefix}_released"),
        "wait_seconds": _safe_float(
            acquired.get("wait_seconds") or timed_out.get("wait_seconds"), 0.0
        ),
        "release_success": bool(released.get("success")),
        "release_attempt": _safe_int(released.get("attempt"), 0),
        "release_total_attempts": _safe_int(released.get("total_attempts"), 0),
    }


def _normalize_status(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    normalized = raw.rsplit(".", 1)[-1].lower()
    if normalized in {"success", "checked", "failed"}:
        return normalized
    return raw.lower()
