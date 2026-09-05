"""
签到任务 API 路由
提供签到任务的 REST API
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Union

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictBool, StrictFloat, StrictInt, StrictStr, validator
from sqlalchemy.orm import Session

from backend.core.auth import get_current_user, verify_token
from backend.core.database import get_db
from backend.core.validators import ValidationError, validate_account_name
from backend.repositories.sign_task_config_repo import get_sign_task_config_repo
from backend.repositories.sign_task_history_repo import get_sign_task_history_repo
from backend.services.sign_task_event_presets import validate_range_window_config
from backend.services.sign_task_runtime_contract import (
    EVENT_CHAT_RUNTIME_CONFIG_FIELDS,
    EVENT_NUMERIC_BUDGET_MINIMUMS,
    normalize_sign_actions,
)
from backend.services.sign_tasks import SignTaskService, get_sign_task_service

router = APIRouter()


_BUDGET_MIN = EVENT_NUMERIC_BUDGET_MINIMUMS
_CHAT_RUNTIME_CONFIG_FIELDS = EVENT_CHAT_RUNTIME_CONFIG_FIELDS
_CHAT_OPTIONAL_NUMERIC_CONFIG_FIELDS = ("delete_after", *tuple(_BUDGET_MIN))
_TASK_OPTIONAL_NUMERIC_CONFIG_FIELDS = ("random_seconds", "sign_interval", "retry_count")
_EXECUTION_MODES = {"fixed", "range"}


def _valid_account_name(account_name: str) -> str:
    try:
        return validate_account_name(account_name)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _valid_optional_account_name(account_name: Optional[str]) -> Optional[str]:
    return _valid_account_name(account_name) if account_name else None


# Pydantic 模型定义

DiagnosticPrimitive = Union[StrictBool, StrictInt, StrictFloat, StrictStr, None]


class ActionBase(BaseModel):
    """动作基类"""

    action: int = Field(..., description="动作类型")


class SendTextAction(ActionBase):
    """发送文本动作"""

    action: int = Field(1, description="动作类型：1=发送文本")
    text: str = Field(..., description="要发送的文本")


class SendDiceAction(ActionBase):
    """发送骰子动作"""

    action: int = Field(2, description="动作类型：2=发送骰子")
    dice: str = Field(..., description="骰子表情")


class ClickKeyboardAction(ActionBase):
    """点击键盘按钮动作"""

    action: int = Field(3, description="动作类型：3=点击按钮")
    text: str = Field(..., description="按钮文本")


class ChooseOptionByImageAction(ActionBase):
    """AI 图片识别动作"""

    action: int = Field(4, description="动作类型：4=AI 图片识别")


class ReplyByCalculationAction(ActionBase):
    """AI 计算题动作"""

    action: int = Field(5, description="动作类型：5=AI 计算题")


class ChatConfig(BaseModel):
    """Chat 配置"""

    chat_id: int = Field(..., description="Chat ID")
    name: str = Field("", description="Chat 名称")
    actions: List[Dict[str, Any]] = Field(..., description="动作列表")
    delete_after: Optional[int] = Field(None, ge=0, description="删除延迟（秒）")
    event_timeout: Optional[float] = Field(None, ge=_BUDGET_MIN["event_timeout"], description="事件引擎总等待秒数")
    event_retries: Optional[int] = Field(None, ge=_BUDGET_MIN["event_retries"], description="事件引擎内部重试次数")
    event_retry_wait: Optional[float] = Field(None, ge=_BUDGET_MIN["event_retry_wait"], description="事件引擎重试等待秒数")
    event_history_limit: Optional[int] = Field(None, ge=_BUDGET_MIN["event_history_limit"], description="事件引擎历史救援扫描条数")
    event_history_failure_threshold: Optional[int] = Field(None, ge=_BUDGET_MIN["event_history_failure_threshold"], description="事件引擎连续历史扫描失败后暂停补漏阈值，0 表示不暂停")
    event_history_rescue_interval: Optional[float] = Field(None, ge=_BUDGET_MIN["event_history_rescue_interval"], description="事件引擎历史补漏扫描间隔秒数")
    event_history_rpc_timeout: Optional[float] = Field(None, ge=_BUDGET_MIN["event_history_rpc_timeout"], description="事件引擎读取历史消息 RPC 超时秒数")
    event_history_result_max_age: Optional[float] = Field(None, ge=_BUDGET_MIN["event_history_result_max_age"], description="事件引擎启动历史结果消息最大年龄秒数，0 表示不限制")
    event_action_timeout: Optional[float] = Field(None, ge=_BUDGET_MIN["event_action_timeout"], description="事件引擎单个响应动作超时秒数")
    event_send_timeout: Optional[float] = Field(None, ge=_BUDGET_MIN["event_send_timeout"], description="事件引擎入口/后续发送动作超时秒数")
    event_media_timeout: Optional[float] = Field(None, ge=_BUDGET_MIN["event_media_timeout"], description="事件引擎下载图片/媒体超时秒数")
    event_ai_timeout: Optional[float] = Field(None, ge=_BUDGET_MIN["event_ai_timeout"], description="事件引擎 AI/OCR 调用超时秒数")
    event_callback_timeout: Optional[float] = Field(None, ge=_BUDGET_MIN["event_callback_timeout"], description="事件引擎按钮 callback RPC 超时秒数")
    event_callback_retries: Optional[int] = Field(None, ge=_BUDGET_MIN["event_callback_retries"], description="事件引擎按钮 callback RPC 重试次数")
    event_ai_fallback: Optional[bool] = Field(None, description="事件引擎未知交互 AI 兜底")

    @validator("chat_id", pre=True)
    def validate_chat_id(cls, value):
        if isinstance(value, bool) or value in ("", None):
            raise ValueError("会话 chat_id 必须为非零整数")
        if isinstance(value, float) and not value.is_integer():
            raise ValueError("会话 chat_id 必须为非零整数")
        try:
            chat_id = int(value)
        except (TypeError, ValueError):
            raise ValueError("会话 chat_id 必须为非零整数")
        if chat_id == 0:
            raise ValueError("会话 chat_id 必须为非零整数")
        return chat_id

    @validator("actions")
    def validate_actions(cls, actions):
        return normalize_sign_actions(actions)

    @validator(*_CHAT_RUNTIME_CONFIG_FIELDS, "delete_after", pre=True, always=True)
    def normalize_blank_runtime_config(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @validator(*_CHAT_OPTIONAL_NUMERIC_CONFIG_FIELDS, pre=True, always=True)
    def reject_bool_runtime_numbers(cls, value, field):
        if isinstance(value, bool):
            raise ValueError(f"{field.name} 必须为数字")
        return value

    @validator("event_ai_fallback", pre=True, always=True)
    def reject_numeric_event_ai_fallback(cls, value):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            raise ValueError("event_ai_fallback 必须为布尔值")
        return value


class SignTaskCreate(BaseModel):
    """创建签到任务请求"""

    name: str = Field(..., description="任务名称")
    account_name: str = Field(..., description="关联的账号名称")
    sign_at: str = Field(..., description="签到时间（CRON 表达式）")
    chats: List[ChatConfig] = Field(..., min_items=1, description="Chat 配置列表")
    random_seconds: int = Field(0, ge=0, description="随机延迟秒数")
    sign_interval: Optional[int] = Field(
        None, ge=0, description="签到间隔秒数，留空使用全局配置或随机 1-120 秒"
    )
    retry_count: int = Field(0, ge=0, description="失败重试次数")
    execution_mode: Optional[str] = Field("fixed", description="执行模式: fixed/range")
    range_start: Optional[str] = Field(None, description="随机范围开始时间")
    range_end: Optional[str] = Field(None, description="随机范围结束时间")

    @validator("name")
    def name_must_be_valid_filename(cls, v):
        import re

        if not v or not v.strip():
            raise ValueError("任务名称不能为空")
        # Windows 文件名非法字符检查
        invalid_chars = r'[<>:"/\\|?*]'
        if re.search(invalid_chars, v):
            raise ValueError('任务名称不能包含特殊字符: < > : " / \\ | ? *')
        return v

    @validator("execution_mode", pre=True, always=True)
    def validate_execution_mode(cls, value):
        if value in ("", None):
            return "fixed"
        mode = str(value).strip().lower()
        if mode not in _EXECUTION_MODES:
            raise ValueError("执行模式必须为 fixed 或 range")
        return mode

    @validator(*_TASK_OPTIONAL_NUMERIC_CONFIG_FIELDS, pre=True, always=True)
    def reject_bool_task_numbers(cls, value, field):
        if isinstance(value, bool):
            raise ValueError(f"{field.name} 必须为数字")
        return value


class SignTaskUpdate(BaseModel):
    """更新签到任务请求"""

    sign_at: Optional[str] = Field(None, description="签到时间（CRON 表达式）")
    chats: Optional[List[ChatConfig]] = Field(None, min_items=1, description="Chat 配置列表")
    random_seconds: Optional[int] = Field(None, ge=0, description="随机延迟秒数")
    sign_interval: Optional[int] = Field(None, ge=0, description="签到间隔秒数")
    retry_count: Optional[int] = Field(None, ge=0, description="失败重试次数")
    execution_mode: Optional[str] = Field(None, description="执行模式: fixed/range")
    range_start: Optional[str] = Field(None, description="随机范围开始时间")
    range_end: Optional[str] = Field(None, description="随机范围结束时间")

    @validator("execution_mode", pre=True, always=True)
    def validate_execution_mode(cls, value):
        if value in ("", None):
            return None
        mode = str(value).strip().lower()
        if mode not in _EXECUTION_MODES:
            raise ValueError("执行模式必须为 fixed 或 range")
        return mode

    @validator(*_TASK_OPTIONAL_NUMERIC_CONFIG_FIELDS, pre=True, always=True)
    def reject_bool_task_numbers(cls, value, field):
        if isinstance(value, bool):
            raise ValueError(f"{field.name} 必须为数字")
        return value


class SignTaskEnabledUpdate(BaseModel):
    """切换任务自动调度状态"""

    account_name: str = Field(..., description="关联的账号名称")
    enabled: StrictBool = Field(..., description="是否启用自动调度")


class LastRunInfo(BaseModel):
    """最后执行信息"""

    time: str
    success: bool
    message: str = ""
    flow_event_counts: Dict[str, int] = Field(default_factory=dict)
    run_summary: Dict[str, Any] = Field(default_factory=dict)


class PublicRunSummarySection(BaseModel):
    """Permissive public run-summary section.

    The worker may add new diagnostic keys over time; API models keep unknown
    keys instead of stripping them so older frontends and external scripts stay
    compatible.
    """

    class Config:
        extra = "allow"


class PublicRunSummaryRetry(PublicRunSummarySection):
    last_event: Optional[str] = None
    last_reason: Optional[str] = None
    last_retry_count: Optional[int] = None
    last_budget_remaining: Optional[int] = None
    last_attempt_epoch: Optional[int] = None
    last_source: Optional[str] = None
    last_message_id: Optional[int] = None
    last_trigger: Optional[str] = None
    attempt_state_resets: Optional[int] = None
    last_reset_previous_attempt_epoch: Optional[int] = None
    last_reset_attempt_epoch: Optional[int] = None
    last_reset_cleared_processed_versions: Optional[int] = None
    last_reset_cleared_sent_captcha_versions: Optional[int] = None
    last_reset_cleared_clicked_versions: Optional[int] = None
    last_reset_cleared_history_duplicates: Optional[int] = None
    last_reset_cleared_history_filtered: Optional[int] = None
    last_reset_cleared_history_unhandled: Optional[int] = None
    last_reset_cleared_history_unhandled_duplicates: Optional[int] = None
    last_reset_cleared_history_tracked_message_ids: Optional[int] = None
    last_current_response_index: Optional[int] = None
    last_current_action: Optional[str] = None
    last_retry_pending: Optional[bool] = None
    scheduled_count: Optional[int] = None
    started_count: Optional[int] = None
    completed_count: Optional[int] = None
    cancelled_count: Optional[int] = None
    suppressed_count: Optional[int] = None
    initial_send_failed_count: Optional[int] = None
    initial_send_error_count: Optional[int] = None
    limit_exceeded: Optional[bool] = None
    limit_exceeded_count: Optional[int] = None
    max_inline_retries: Optional[int] = None
    task_configured_count: Optional[int] = None
    task_configured_total_attempts: Optional[int] = None
    task_last_event: Optional[str] = None
    task_scheduled_count: Optional[int] = None
    task_started_count: Optional[int] = None
    task_last_attempt: Optional[int] = None
    task_last_total_attempts: Optional[int] = None
    task_last_retry_count: Optional[int] = None
    task_last_budget_remaining: Optional[int] = None
    task_last_error_type: Optional[str] = None
    task_last_retryable: Optional[bool] = None


class PublicRunSummaryCallbacks(PublicRunSummarySection):
    confirmed: Optional[int] = None
    trusted_timeout: Optional[int] = None
    data_invalid_after_timeout: Optional[int] = None
    unconfirmed: Optional[int] = None
    total_results: Optional[int] = None
    outer_timeouts: Optional[int] = None
    exceptions: Optional[int] = None
    released_for_retry: Optional[int] = None
    callback_texts: Optional[int] = None
    stale_callback_texts: Optional[int] = None
    last_status: Optional[str] = None
    last_reason: Optional[str] = None
    last_source: Optional[str] = None
    last_current_response_index: Optional[int] = None
    last_current_action: Optional[str] = None
    last_retry_pending: Optional[bool] = None
    last_retry_budget_remaining: Optional[int] = None
    last_message_id: Optional[int] = None
    last_button_text: Optional[str] = None
    last_confirmed: Optional[bool] = None
    last_attempt: Optional[int] = None
    last_max_retries: Optional[int] = None
    last_timeout: Optional[float] = None
    last_error_type: Optional[str] = None
    last_had_timeout: Optional[bool] = None
    last_trusted_consumed: Optional[bool] = None
    last_has_callback_text: Optional[bool] = None
    last_outer_timeout_source: Optional[str] = None
    last_outer_timeout_scope: Optional[str] = None
    last_outer_operation_timeout: Optional[float] = None
    last_outer_timeout_attempt_epoch: Optional[int] = None
    last_outer_timeout_current_response_index: Optional[int] = None
    last_outer_timeout_current_action: Optional[str] = None
    last_outer_timeout_retry_count: Optional[int] = None
    last_outer_timeout_retry_budget_remaining: Optional[int] = None
    last_outer_timeout_retry_pending: Optional[bool] = None
    last_exception_source: Optional[str] = None
    last_exception_error_type: Optional[str] = None
    last_exception_operation_timeout: Optional[float] = None
    last_unconfirmed_source: Optional[str] = None
    last_unconfirmed_message_id: Optional[int] = None
    last_unconfirmed_button_text: Optional[str] = None
    last_unconfirmed_status: Optional[str] = None
    last_unconfirmed_reason: Optional[str] = None
    last_unconfirmed_attempt_epoch: Optional[int] = None
    last_unconfirmed_current_response_index: Optional[int] = None
    last_unconfirmed_current_action: Optional[str] = None
    last_unconfirmed_retry_count: Optional[int] = None
    last_unconfirmed_retry_budget_remaining: Optional[int] = None
    last_unconfirmed_retry_pending: Optional[bool] = None
    last_unconfirmed_attempt: Optional[int] = None
    last_unconfirmed_max_retries: Optional[int] = None
    last_unconfirmed_timeout: Optional[float] = None
    last_unconfirmed_error_type: Optional[str] = None
    last_unconfirmed_had_timeout: Optional[bool] = None
    last_released_source: Optional[str] = None
    last_released_message_id: Optional[int] = None
    last_released_button_text: Optional[str] = None
    last_released_status: Optional[str] = None
    last_released_attempt_epoch: Optional[int] = None
    last_released_current_response_index: Optional[int] = None
    last_released_current_action: Optional[str] = None
    last_released_retry_count: Optional[int] = None
    last_released_retry_budget_remaining: Optional[int] = None
    last_released_attempt: Optional[int] = None
    last_released_max_retries: Optional[int] = None
    last_released_timeout: Optional[float] = None
    last_released_retry_pending: Optional[bool] = None
    last_released_clicked_versions: Optional[int] = None
    last_stale_callback_text_message_id: Optional[int] = None
    last_stale_callback_text_attempt_epoch: Optional[int] = None
    last_stale_callback_text_current_epoch: Optional[int] = None


class PublicRunSummaryResultMatch(PublicRunSummarySection):
    event: Optional[str] = None
    matched: Optional[bool] = None
    status: Optional[str] = None
    source: Optional[str] = None
    message_id: Optional[int] = None
    keyword: Optional[str] = None
    attempt_epoch: Optional[int] = None
    current_response_index: Optional[int] = None
    current_action: Optional[str] = None
    retry_count: Optional[int] = None
    retry_budget_remaining: Optional[int] = None
    retry_pending: Optional[bool] = None


class PublicRunSummaryMessages(PublicRunSummarySection):
    processed_versions: Optional[int] = None
    processing_versions: Optional[int] = None
    sent_captcha_versions: Optional[int] = None
    captcha_result_text_preemptions: Optional[int] = None
    response_messages_sent: Optional[int] = None
    response_actions_advanced: Optional[int] = None
    last_response_action_from_index: Optional[int] = None
    last_response_action_to_index: Optional[int] = None
    last_response_action_source: Optional[str] = None
    last_response_action_reason: Optional[str] = None
    last_response_action_attempt_epoch: Optional[int] = None
    last_response_action_message_id: Optional[int] = None
    response_actions_not_advanced: Optional[int] = None
    last_response_action_not_advanced_index: Optional[int] = None
    last_response_action_not_advanced_source: Optional[str] = None
    last_response_action_not_advanced_reason: Optional[str] = None
    last_response_action_not_advanced_finished: Optional[bool] = None
    last_response_action_not_advanced_retry_pending: Optional[bool] = None
    last_response_action_not_advanced_attempt_epoch: Optional[int] = None
    last_response_action_not_advanced_message_id: Optional[int] = None
    message_retryable_errors: Optional[int] = None
    last_message_retryable_message_id: Optional[int] = None
    last_message_retryable_error_type: Optional[str] = None
    last_message_retryable_operation: Optional[str] = None
    last_message_retryable_timeout_scope: Optional[str] = None
    last_message_retryable_operation_timeout: Optional[float] = None
    last_message_retryable_attempt_epoch: Optional[int] = None
    last_message_retryable_current_response_index: Optional[int] = None
    last_message_retryable_current_action: Optional[str] = None
    last_message_retryable_retry_count: Optional[int] = None
    last_message_retryable_retry_budget_remaining: Optional[int] = None
    last_message_retryable_retry_pending: Optional[bool] = None
    clicked_versions: Optional[int] = None
    skipped_clicked_duplicate: Optional[int] = None
    skipped_duplicate: Optional[int] = None
    skipped_concurrent_duplicate: Optional[int] = None
    skipped_finished: Optional[int] = None
    skipped_non_inbound: Optional[int] = None
    message_processing_cancelled: Optional[int] = None
    last_message_processing_cancelled_message_id: Optional[int] = None
    last_message_processing_cancelled_version_hash: Optional[str] = None
    last_message_processing_cancelled_action: Optional[str] = None
    last_message_processing_cancelled_attempt_epoch: Optional[int] = None
    last_message_processing_cancelled_retry_pending: Optional[bool] = None
    last_message_processing_cancelled_will_release: Optional[bool] = None
    stale_attempt_processed_marks: Optional[int] = None
    last_stale_attempt_message_epoch: Optional[int] = None
    last_stale_attempt_current_epoch: Optional[int] = None
    last_skip_reason: Optional[str] = None
    last_skip_message_id: Optional[int] = None
    last_skip_message_version_hash: Optional[str] = None
    last_skip_attempt_epoch: Optional[int] = None
    last_skip_current_response_index: Optional[int] = None
    last_skip_current_action: Optional[str] = None
    last_skip_retry_count: Optional[int] = None
    last_skip_retry_budget_remaining: Optional[int] = None
    last_skip_retry_pending: Optional[bool] = None
    unhandled: Optional[int] = None


class PublicRunSummaryHistory(PublicRunSummarySection):
    startup_scans: Optional[int] = None
    rescue_scans: Optional[int] = None
    failed_scans: Optional[int] = None
    messages_handled: Optional[int] = None
    duplicate_messages: Optional[int] = None
    messages_seen: Optional[int] = None
    messages_allowed: Optional[int] = None
    tracked_rechecks: Optional[int] = None
    concurrent_skipped: Optional[int] = None
    cancelled_scans: Optional[int] = None
    scan_in_progress: Optional[bool] = None
    rescue_suspended: Optional[bool] = None
    circuit_opened: Optional[int] = None
    consecutive_failures: Optional[int] = None
    expired_messages: Optional[int] = None
    filtered_before_entry: Optional[int] = None
    filtered_expired: Optional[int] = None
    hard_failures_skipped: Optional[int] = None
    unhandled_duplicates: Optional[int] = None
    last_scan_status: Optional[str] = None
    last_scan_source: Optional[str] = None
    last_scan_message_count: Optional[int] = None
    last_scan_allowed_count: Optional[int] = None
    last_scan_handled_count: Optional[int] = None
    last_scan_error_type: Optional[str] = None
    last_scan_attempt_epoch: Optional[int] = None
    last_scan_current_response_index: Optional[int] = None
    last_scan_current_action: Optional[str] = None
    last_scan_retry_count: Optional[int] = None
    last_scan_retry_budget_remaining: Optional[int] = None
    last_scan_retry_pending: Optional[bool] = None
    last_failed_source: Optional[str] = None
    last_failed_operation: Optional[str] = None
    last_failed_timeout_scope: Optional[str] = None
    last_failed_error_type: Optional[str] = None
    last_failed_timeout: Optional[float] = None
    last_failed_scan_count: Optional[int] = None
    last_failure_scan_in_progress: Optional[bool] = None
    last_failure_blocks_main_flow: Optional[bool] = None
    last_failure_retry_pending: Optional[bool] = None
    last_failure_will_open_circuit: Optional[bool] = None
    last_failure_rescue_will_continue: Optional[bool] = None
    last_suspended_source: Optional[str] = None
    last_suspended_status: Optional[str] = None
    last_suspended_attempt_epoch: Optional[int] = None
    last_suspended_current_response_index: Optional[int] = None
    last_suspended_current_action: Optional[str] = None
    last_suspended_retry_count: Optional[int] = None
    last_suspended_retry_budget_remaining: Optional[int] = None
    last_suspended_retry_pending: Optional[bool] = None


class PublicRunSummaryTimeouts(PublicRunSummarySection):
    timeout_count_total: Optional[int] = None
    event: Optional[int] = None
    response_action: Optional[int] = None
    callback_outer: Optional[int] = None
    send_rpc: Optional[int] = None
    media_rpc: Optional[int] = None
    ai_rpc: Optional[int] = None
    task_run: Optional[int] = None
    client_rpc: Optional[int] = None
    client_cleanup_rpc: Optional[int] = None
    client_cleanup_rpc_last_timeout: Optional[float] = None
    client_rpc_late_cancelled: Optional[int] = None
    client_rpc_late_completed: Optional[int] = None
    client_rpc_late_exception: Optional[int] = None
    client_rpc_last_late_event: Optional[str] = None
    client_rpc_last_late_operation: Optional[str] = None
    client_rpc_last_late_timeout_scope: Optional[str] = None
    client_rpc_last_late_error_type: Optional[str] = None
    client_rpc_last_late_timeout: Optional[float] = None
    client_startup_retry: Optional[int] = None
    client_startup_retry_last_attempt: Optional[int] = None
    client_startup_retry_total_attempts: Optional[int] = None
    client_startup_retry_budget_remaining: Optional[int] = None
    client_startup_retry_wait_seconds: Optional[float] = None
    client_startup_retry_cleanup_attempted: Optional[bool] = None
    client_startup_retry_error_type: Optional[str] = None
    client_startup_retry_reason: Optional[str] = None
    client_startup_lock: Optional[int] = None
    client_startup_lock_timeout_seconds: Optional[float] = None
    client_exit_lock: Optional[int] = None
    client_exit_lock_timeout_seconds: Optional[float] = None
    client_close_lock: Optional[int] = None
    client_close_lock_timeout_seconds: Optional[float] = None
    task_run_late_cancelled: Optional[int] = None
    task_run_late_completed: Optional[int] = None
    task_run_late_exception: Optional[int] = None
    task_run_last_late_event: Optional[str] = None
    task_run_last_late_operation: Optional[str] = None
    task_run_last_late_timeout_scope: Optional[str] = None
    task_run_last_late_error_type: Optional[str] = None
    task_run_last_late_timeout_seconds: Optional[float] = None
    task_run_last_late_attempt: Optional[int] = None
    task_run_last_late_total_attempts: Optional[int] = None
    task_run_cancelled: Optional[bool] = None
    task_run_cleanup_expected: Optional[bool] = None
    task_run_operation: Optional[str] = None
    task_run_timeout_scope: Optional[str] = None
    task_run_timeout_seconds: Optional[float] = None
    task_run_attempt: Optional[int] = None
    task_run_total_attempts: Optional[int] = None
    late_cancelled: Optional[int] = None
    late_completed: Optional[int] = None
    late_exception: Optional[int] = None
    last_late_event: Optional[str] = None
    last_late_operation: Optional[str] = None
    last_late_timeout_scope: Optional[str] = None
    last_late_source: Optional[str] = None
    last_late_message_id: Optional[int] = None
    last_late_error_type: Optional[str] = None
    last_late_timeout: Optional[float] = None
    last_late_cancelled_by_parent: Optional[bool] = None
    last_late_attempt_epoch: Optional[int] = None
    last_late_current_response_index: Optional[int] = None
    last_late_current_action: Optional[str] = None
    last_late_retry_count: Optional[int] = None
    last_late_retry_budget_remaining: Optional[int] = None
    last_late_retry_pending: Optional[bool] = None
    last_rpc_event: Optional[str] = None
    last_rpc_kind: Optional[str] = None
    last_rpc_operation: Optional[str] = None
    last_rpc_timeout_scope: Optional[str] = None
    last_rpc_source: Optional[str] = None
    last_rpc_message_id: Optional[int] = None
    last_rpc_source_message_id: Optional[int] = None
    last_rpc_error_type: Optional[str] = None
    last_rpc_timeout: Optional[float] = None


class PublicRunSummaryRuntime(PublicRunSummarySection):
    runtime_config_key: Optional[str] = None
    chat_count: Optional[int] = None
    event_chat_count: Optional[int] = None
    configured_action_count: Optional[int] = None
    send_action_count: Optional[int] = None
    button_action_count: Optional[int] = None
    image_option_action_count: Optional[int] = None
    captcha_action_count: Optional[int] = None
    captcha_caption_pattern_count: Optional[int] = None
    captcha_length_constrained_count: Optional[int] = None
    captcha_charset_constrained_count: Optional[int] = None
    captcha_reply_to_message_count: Optional[int] = None
    assertion_action_count: Optional[int] = None
    requires_result_assertion: Optional[bool] = None
    event_timeout: Optional[float] = None
    action_timeout: Optional[float] = None
    send_timeout: Optional[float] = None
    media_timeout: Optional[float] = None
    ai_timeout: Optional[float] = None
    callback_timeout: Optional[float] = None
    callback_retries: Optional[int] = None
    ai_fallback_enabled: Optional[bool] = None
    retry_wait: Optional[float] = None
    max_inline_retries: Optional[int] = None
    history_limit: Optional[int] = None
    history_rescue_interval: Optional[float] = None
    history_rpc_timeout: Optional[float] = None
    history_result_max_age: Optional[float] = None
    history_failure_threshold: Optional[int] = None
    ai_fallback_enabled_count: Optional[int] = None
    ai_fallback_disabled_count: Optional[int] = None


class PublicRunSummaryCleanup(PublicRunSummarySection):
    started: Optional[bool] = None
    completed: Optional[bool] = None
    failed: Optional[bool] = None
    last_event: Optional[str] = None
    last_attempt: Optional[int] = None
    last_total_attempts: Optional[int] = None
    last_success: Optional[bool] = None
    last_operation: Optional[str] = None
    last_timeout_scope: Optional[str] = None
    error_type: Optional[str] = None
    timeout_seconds: Optional[float] = None
    manager_lock_present: Optional[bool] = None
    manager_lock_acquired: Optional[bool] = None
    manager_lock_wait_timeout: Optional[bool] = None
    manager_lock_timeout_seconds: Optional[float] = None
    manager_force_cleanup: Optional[bool] = None
    manager_client_found: Optional[bool] = None
    manager_cleanup_attempted: Optional[bool] = None
    manager_cleanup_error_type: Optional[str] = None
    rpc_attempts: Optional[int] = None
    rpc_timeouts: Optional[int] = None
    rpc_errors: Optional[int] = None
    last_rpc_error_type: Optional[str] = None
    last_rpc_timeout: Optional[float] = None
    rpc_late_cancelled: Optional[int] = None
    rpc_late_completed: Optional[int] = None
    rpc_late_exception: Optional[int] = None
    last_rpc_late_event: Optional[str] = None
    last_rpc_late_error_type: Optional[str] = None
    last_rpc_late_timeout: Optional[float] = None
    deferred_cancellations: Optional[int] = None
    last_deferred_cancel_attempt: Optional[int] = None
    last_deferred_cancel_total_attempts: Optional[int] = None
    last_deferred_cancel_success: Optional[bool] = None
    last_deferred_cancel_timeout_seconds: Optional[float] = None
    late_cancelled: Optional[int] = None
    late_completed: Optional[int] = None
    late_exception: Optional[int] = None
    last_late_event: Optional[str] = None
    last_late_operation: Optional[str] = None
    last_late_timeout_scope: Optional[str] = None
    last_late_error_type: Optional[str] = None
    last_late_timeout_seconds: Optional[float] = None
    last_late_attempt: Optional[int] = None
    last_late_total_attempts: Optional[int] = None
    last_late_success: Optional[bool] = None


class PublicRunSummaryLock(PublicRunSummarySection):
    waited: Optional[bool] = None
    acquired: Optional[bool] = None
    wait_timeout: Optional[bool] = None
    last_operation: Optional[str] = None
    last_timeout_scope: Optional[str] = None
    wait_timeout_seconds: Optional[float] = None
    released: Optional[bool] = None
    wait_seconds: Optional[float] = None
    release_success: Optional[bool] = None
    release_attempt: Optional[int] = None
    release_total_attempts: Optional[int] = None


class PublicRunSummaryPersistence(PublicRunSummarySection):
    run_info_save_failed: Optional[bool] = None
    run_info_save_error_type: Optional[str] = None


class PublicRunSummary(BaseModel):
    success: Optional[bool] = None
    status: Optional[str] = None
    error: Optional[str] = None
    attempt: Optional[int] = None
    total_attempts: Optional[int] = None
    retry_count: Optional[int] = None
    retry_budget_remaining: Optional[int] = None
    retry_suppressed_count: Optional[int] = None
    current_response_index: Optional[int] = None
    response_action_count: Optional[int] = None
    current_action: Optional[str] = None
    attempt_epoch: Optional[int] = None
    result_match: Optional[PublicRunSummaryResultMatch] = None
    retry: Optional[PublicRunSummaryRetry] = None
    callbacks: Optional[PublicRunSummaryCallbacks] = None
    messages: Optional[PublicRunSummaryMessages] = None
    history: Optional[PublicRunSummaryHistory] = None
    timeouts: Optional[PublicRunSummaryTimeouts] = None
    runtime: Optional[PublicRunSummaryRuntime] = None
    cleanup: Optional[PublicRunSummaryCleanup] = None
    persistence: Optional[PublicRunSummaryPersistence] = None
    account_lock: Optional[PublicRunSummaryLock] = None
    global_concurrency: Optional[PublicRunSummaryLock] = None
    error_type: Optional[str] = None
    error_timeout_scope: Optional[str] = None

    class Config:
        extra = "allow"


class SignTaskOut(BaseModel):
    """签到任务输出"""

    name: str
    account_name: str = ""
    sign_at: str
    chats: List[Dict[str, Any]]
    random_seconds: int
    sign_interval: int
    retry_count: int = 0
    engine: Optional[str] = "event"
    enabled: bool
    last_run: Optional[LastRunInfo] = None
    execution_mode: Optional[str] = "fixed"
    range_start: Optional[str] = None
    range_end: Optional[str] = None
    next_scheduled_at: Optional[str] = None


class ChatOut(BaseModel):
    """Chat 输出"""

    id: int
    title: Optional[str] = None
    username: Optional[str] = None
    type: str
    first_name: Optional[str] = None


class ChatSearchResponse(BaseModel):
    """Chat 搜索结果"""

    items: List[ChatOut]
    total: int
    limit: int
    offset: int


class ChatCacheResponse(BaseModel):
    items: List[ChatOut]
    last_cached_at: Optional[str] = None
    cache_ttl_minutes: int = 1440
    expired: bool = True
    count: int = 0


class ChatCacheMetaResponse(BaseModel):
    account_name: str
    cache_ttl_minutes: int
    last_cached_at: Optional[str] = None
    expired: bool = True
    count: int = 0


class RunTaskResult(BaseModel):
    """运行任务结果"""

    success: bool
    output: str
    error: str
    run_summary: Dict[str, Any] = Field(default_factory=dict)
    started: bool = False
    code: str = ""


class TaskHistoryFlowItem(BaseModel):
    ts: str = ""
    level: str = "info"
    stage: str = "task"
    event: str = "info"
    text: str = ""
    meta: Dict[str, Any] = Field(default_factory=dict)
    text_visible: bool = True


class TaskHistoryDiagnosticCheck(BaseModel):
    id: str = ""
    label: str = ""
    status: str = "unknown"
    detail: str = ""


class TaskHistoryDiagnostics(BaseModel):
    status: str = "unknown"
    summary: str = ""
    checks: List[TaskHistoryDiagnosticCheck] = Field(default_factory=list)
    milestones: Dict[str, DiagnosticPrimitive] = Field(default_factory=dict)


class TaskHistoryItem(BaseModel):
    time: str
    success: bool
    message: str = ""
    flow_logs: List[str] = Field(default_factory=list)
    flow_items: List[TaskHistoryFlowItem] = Field(default_factory=list)
    flow_event_counts: Dict[str, int] = Field(default_factory=dict)
    flow_truncated: bool = False
    flow_line_count: int = 0
    run_summary: Dict[str, Any] = Field(default_factory=dict)
    diagnostics: Optional[TaskHistoryDiagnostics] = None


class SchedulerSignTaskStatus(BaseModel):
    job_id: str
    account_name: str
    task_name: str
    enabled: bool
    execution_mode: str = "fixed"
    schedule: str = ""
    next_run: Optional[str] = None
    next_scheduled_at: Optional[str] = None
    effective_next_run: Optional[str] = None
    execution_job_exists: bool = False
    job_exists: bool = False


class SchedulerStatusOut(BaseModel):
    timezone: str
    running: bool
    total_jobs: int
    sign_job_count: int
    sign_tasks: List[SchedulerSignTaskStatus] = Field(default_factory=list)


class EventEngineDiagnosticRunOut(BaseModel):
    status: str = "unknown"
    success: bool = False
    time: str = ""
    age_hours: Optional[float] = None
    fresh: bool = True
    message: str = ""
    event_counts: Dict[str, int] = Field(default_factory=dict)
    run_summary: Dict[str, Any] = Field(default_factory=dict)
    diagnostics: TaskHistoryDiagnostics = Field(default_factory=TaskHistoryDiagnostics)

    class Config:
        extra = "allow"


class EventEngineDiagnosticConfigCheckOut(BaseModel):
    id: str = ""
    label: str = ""
    status: str = "unknown"
    detail: str = ""

    class Config:
        extra = "allow"


class EventEngineDiagnosticTaskOut(BaseModel):
    task_name: str = ""
    account_name: str = ""
    engine: str = "event"
    status: str = "missing"
    config_status: str = "missing"
    config_checks: List[EventEngineDiagnosticConfigCheckOut] = Field(default_factory=list)
    run_status: str = "missing"
    latest_time: str = ""
    latest_event_counts: Dict[str, int] = Field(default_factory=dict)
    latest_run_summary: Dict[str, Any] = Field(default_factory=dict)
    latest_summary: str = ""
    runs: List[EventEngineDiagnosticRunOut] = Field(default_factory=list)

    class Config:
        extra = "allow"


class EventEngineDiagnosticTargetOut(BaseModel):
    id: str = ""
    label: str = ""
    status: str = "missing"
    summary: str = ""
    tasks: List[EventEngineDiagnosticTaskOut] = Field(default_factory=list)

    class Config:
        extra = "allow"


class EventEngineDiagnosticReportOut(BaseModel):
    status: str = "missing"
    generated_at: str = ""
    max_age_hours: Optional[float] = None
    task_count: int = 0
    targets: List[EventEngineDiagnosticTargetOut] = Field(default_factory=list)
    source: Dict[str, Any] = Field(default_factory=dict)
    hint: Optional[str] = None

    class Config:
        extra = "allow"


# API 路由


@router.get("", response_model=List[SignTaskOut])
def list_sign_tasks(
    account_name: Optional[str] = None,
    current_user=Depends(get_current_user),
    service: SignTaskService = Depends(get_sign_task_service),
):
    """
    获取所有签到任务列表

    Args:
        account_name: 可选，按账号名筛选任务
    """
    account_name = _valid_optional_account_name(account_name)
    tasks = service.list_tasks(account_name=account_name)
    return tasks


@router.get("/scheduler/status", response_model=SchedulerStatusOut)
def get_scheduler_status_api(
    account_name: Optional[str] = None,
    current_user=Depends(get_current_user),
):
    from backend.scheduler import get_scheduler_status

    account_name = _valid_optional_account_name(account_name)
    return get_scheduler_status(account_name=account_name)


@router.get("/canary/report", response_model=EventEngineDiagnosticReportOut)
def get_canary_report_api(
    account_name: Optional[str] = None,
    history_limit: int = Query(1, ge=1, le=20),
    max_age_hours: float = Query(36.0, ge=0),
    current_user=Depends(get_current_user),
):
    """兼容入口：汇总当前任务的事件引擎诊断报告。"""

    account_name = _valid_optional_account_name(account_name)
    from backend.core.config import get_settings
    from backend.services.sign_task_canary import generate_canary_report

    settings = get_settings()
    return generate_canary_report(
        config_repo=get_sign_task_config_repo(),
        history_repo=get_sign_task_history_repo(),
        account_name=account_name,
        history_limit=history_limit,
        max_age_hours=max_age_hours,
        source={
            "database_url": settings.database_url,
            "data_dir": str(settings.data_dir) if settings.data_dir else "",
            "resolved_base_dir": str(settings.resolve_base_dir()),
        },
    )


@router.get("/event-engine/report", response_model=EventEngineDiagnosticReportOut)
def get_event_engine_report_api(
    account_name: Optional[str] = None,
    history_limit: int = Query(1, ge=1, le=20),
    max_age_hours: float = Query(36.0, ge=0),
    current_user=Depends(get_current_user),
):
    """汇总当前账号真实签到任务的事件引擎诊断报告。"""

    account_name = _valid_optional_account_name(account_name)
    from backend.core.config import get_settings
    from backend.services.sign_task_canary import generate_event_engine_diagnostic_report

    settings = get_settings()
    return generate_event_engine_diagnostic_report(
        config_repo=get_sign_task_config_repo(),
        history_repo=get_sign_task_history_repo(),
        account_name=account_name,
        history_limit=history_limit,
        max_age_hours=max_age_hours,
        source={
            "database_url": settings.database_url,
            "data_dir": str(settings.data_dir) if settings.data_dir else "",
            "resolved_base_dir": str(settings.resolve_base_dir()),
        },
    )


@router.post("", response_model=SignTaskOut, status_code=status.HTTP_201_CREATED)
async def create_sign_task(
    payload: SignTaskCreate,
    current_user=Depends(get_current_user),
    service: SignTaskService = Depends(get_sign_task_service),
):
    """创建新的签到任务"""
    import traceback

    try:
        account_name = _valid_account_name(payload.account_name)
        validate_range_window_config(
            {
                "execution_mode": payload.execution_mode,
                "range_start": payload.range_start,
                "range_end": payload.range_end,
            }
        )
        chats_dict = [chat.dict(exclude_none=True) for chat in payload.chats]

        return await service.create_task_and_sync(
            task_name=payload.name,
            account_name=account_name,
            sign_at=payload.sign_at,
            chats=chats_dict,
            random_seconds=payload.random_seconds,
            sign_interval=payload.sign_interval,
            retry_count=payload.retry_count,
            execution_mode=payload.execution_mode,
            range_start=payload.range_start,
            range_end=payload.range_end,
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"创建任务失败: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"创建任务失败: {str(e)}")


@router.get("/{task_name}", response_model=SignTaskOut)
def get_sign_task(
    task_name: str,
    account_name: Optional[str] = None,
    current_user=Depends(get_current_user),
    service: SignTaskService = Depends(get_sign_task_service),
):
    account_name = _valid_optional_account_name(account_name)
    task = service.get_task(task_name, account_name=account_name)
    if not task:
        raise HTTPException(status_code=404, detail=f"任务 {task_name} 不存在")
    return task


@router.put("/{task_name}", response_model=SignTaskOut)
async def update_sign_task(
    task_name: str,
    payload: SignTaskUpdate,
    account_name: Optional[str] = None,
    current_user=Depends(get_current_user),
    service: SignTaskService = Depends(get_sign_task_service),
):
    """更新签到任务"""
    try:
        account_name = _valid_optional_account_name(account_name)
        existing = service.get_task(task_name, account_name=account_name)
        if not existing:
            raise HTTPException(status_code=404, detail=f"任务 {task_name} 不存在")

        chats_dict = None
        if payload.chats is not None:
            chats_dict = [chat.dict(exclude_none=True) for chat in payload.chats]
        validate_range_window_config(
            {
                "execution_mode": (
                    payload.execution_mode
                    if payload.execution_mode is not None
                    else existing.get("execution_mode", "fixed")
                ),
                "range_start": (
                    payload.range_start
                    if payload.range_start is not None
                    else existing.get("range_start", "")
                ),
                "range_end": (
                    payload.range_end
                    if payload.range_end is not None
                    else existing.get("range_end", "")
                ),
            }
        )

        return await service.update_task_and_sync(
            task_name=task_name,
            sign_at=payload.sign_at,
            chats=chats_dict,
            random_seconds=payload.random_seconds,
            sign_interval=payload.sign_interval,
            retry_count=payload.retry_count,
            account_name=account_name or existing.get("account_name"),
            execution_mode=payload.execution_mode,
            range_start=payload.range_start,
            range_end=payload.range_end,
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback

        print(f"更新任务失败: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"更新任务失败: {str(e)}")


@router.patch("/{task_name}/enabled", response_model=SignTaskOut)
async def set_sign_task_enabled(
    task_name: str,
    payload: SignTaskEnabledUpdate,
    current_user=Depends(get_current_user),
    service: SignTaskService = Depends(get_sign_task_service),
):
    """暂停或恢复任务自动调度；不影响手动运行。"""
    try:
        return await service.set_task_enabled_and_sync(
            task_name=task_name,
            account_name=_valid_account_name(payload.account_name),
            enabled=payload.enabled,
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        import traceback

        print(f"切换任务自动调度失败: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"切换任务自动调度失败: {str(e)}")


@router.delete("/{task_name}", status_code=status.HTTP_200_OK)
async def delete_sign_task(
    task_name: str,
    account_name: Optional[str] = None,
    current_user=Depends(get_current_user),
    service: SignTaskService = Depends(get_sign_task_service),
):
    """删除签到任务"""
    if not account_name:
        raise HTTPException(status_code=400, detail="删除任务必须指定 account_name")

    account_name = _valid_account_name(account_name)
    success = await service.delete_task_and_sync(
        task_name,
        account_name=account_name,
    )
    if not success:
        raise HTTPException(status_code=404, detail=f"任务 {task_name} 不存在")

    return {"ok": True}


@router.get("/{task_name}/status")
def get_sign_task_status(
    task_name: str,
    account_name: str,
    current_user=Depends(get_current_user),
    service: SignTaskService = Depends(get_sign_task_service),
):
    account_name = _valid_account_name(account_name)
    if service.get_task(task_name, account_name) is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"running": service.is_task_running(task_name, account_name=account_name)}


@router.post("/{task_name}/run", response_model=RunTaskResult)
async def run_sign_task(
    task_name: str,
    account_name: str,
    current_user=Depends(get_current_user),
    service: SignTaskService = Depends(get_sign_task_service),
):
    """手动运行签到任务"""
    try:
        account_name = _valid_account_name(account_name)
        return await service.start_task_in_background(
            account_name,
            task_name,
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{task_name}/logs", response_model=List[str])
def get_sign_task_logs(
    task_name: str,
    account_name: str | None = None,
    current_user=Depends(get_current_user),
    service: SignTaskService = Depends(get_sign_task_service),
):
    account_name = _valid_optional_account_name(account_name)
    logs = service.get_active_logs(task_name, account_name=account_name)
    return logs


@router.get("/{task_name}/history", response_model=List[TaskHistoryItem])
def get_sign_task_history(
    task_name: str,
    account_name: str,
    limit: int = Query(20, ge=1, le=200),
    current_user=Depends(get_current_user),
    service: SignTaskService = Depends(get_sign_task_service),
):
    account_name = _valid_account_name(account_name)
    task = service.get_task(task_name, account_name=account_name)
    if not task:
        raise HTTPException(status_code=404, detail=f"任务 {task_name} 不存在")

    return service.get_task_history_logs(
        task_name=task_name,
        account_name=account_name,
        limit=limit,
    )


@router.get("/chats/{account_name}", response_model=ChatCacheResponse)
async def get_account_chats(
    account_name: str,
    force_refresh: bool = False,
    auto_refresh_if_expired: bool = False,
    ensure_exists: bool = False,
    current_user=Depends(get_current_user),
    service: SignTaskService = Depends(get_sign_task_service),
):
    account_name = _valid_account_name(account_name)
    try:
        return await service.get_account_chats(
            account_name,
            force_refresh=force_refresh,
            auto_refresh_if_expired=auto_refresh_if_expired,
            ensure_exists=ensure_exists,
        )
    except ValueError as e:
        detail = str(e)
        if (
            "登录已失效" in detail
            or "session_string" in detail
            or "Session 文件不存在" in detail
        ):
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"detail": detail, "code": "ACCOUNT_SESSION_INVALID"},
            )
        raise HTTPException(status_code=404, detail=detail)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取对话列表失败: {str(e)}")


@router.post("/chats/{account_name}/refresh", response_model=ChatCacheResponse)
async def refresh_account_chats_api(
    account_name: str,
    current_user=Depends(get_current_user),
    service: SignTaskService = Depends(get_sign_task_service),
):
    account_name = _valid_account_name(account_name)
    try:
        return await service.get_account_chats(
            account_name,
            force_refresh=True,
        )
    except ValueError as e:
        detail = str(e)
        if (
            "登录已失效" in detail
            or "session_string" in detail
            or "Session 文件不存在" in detail
        ):
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"detail": detail, "code": "ACCOUNT_SESSION_INVALID"},
            )
        raise HTTPException(status_code=404, detail=detail)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"刷新对话列表失败: {str(e)}")


@router.get("/chats/{account_name}/meta", response_model=ChatCacheMetaResponse)
def get_account_chat_cache_meta(
    account_name: str,
    current_user=Depends(get_current_user),
    service: SignTaskService = Depends(get_sign_task_service),
):
    account_name = _valid_account_name(account_name)
    try:
        return service.ensure_account_chat_cache_meta(account_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取对话缓存信息失败: {str(e)}")


@router.get("/chats/{account_name}/search", response_model=ChatSearchResponse)
def search_account_chats(
    account_name: str,
    q: str = "",
    limit: int = 50,
    offset: int = 0,
    current_user=Depends(get_current_user),
    service: SignTaskService = Depends(get_sign_task_service),
):
    account_name = _valid_account_name(account_name)
    try:
        return service.search_account_chats(
            account_name, q, limit=limit, offset=offset
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索对话列表失败: {str(e)}")


@router.websocket("/ws/{task_name}")
async def sign_task_logs_ws(
    websocket: WebSocket,
    task_name: str,
    account_name: str | None = Query(None),
    token: str = Query(...),
    db: Session = Depends(get_db),
    service: SignTaskService = Depends(get_sign_task_service),
):
    """
    WebSocket 实时推送签到任务日志
    """
    try:
        account_name = _valid_optional_account_name(account_name)
        user = verify_token(token, db)
        if not user:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    last_sent_abs_idx = 0
    try:
        while True:
            is_running = service.is_task_running(
                task_name, account_name=account_name
            )
            base_offset, active_logs = service.get_active_logs_snapshot(
                task_name, account_name=account_name
            )
            end_abs_idx = base_offset + len(active_logs)

            if last_sent_abs_idx < base_offset:
                last_sent_abs_idx = base_offset

            if end_abs_idx > last_sent_abs_idx:
                start_idx = max(last_sent_abs_idx - base_offset, 0)
                new_logs = active_logs[start_idx:]
                await websocket.send_json(
                    {
                        "type": "logs",
                        "data": new_logs,
                        "is_running": is_running,
                    }
                )
                last_sent_abs_idx = end_abs_idx

            if not is_running and last_sent_abs_idx >= end_abs_idx:
                await websocket.send_json({"type": "done", "is_running": False})
                break

            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WS Error: {e}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
