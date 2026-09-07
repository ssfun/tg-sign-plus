from __future__ import annotations

import asyncio
import logging
import os
import time
import traceback
import uuid
from typing import Any, Dict, List

from backend.core.config import get_settings
from backend.services.sign_task_log_context import reset_sign_task_run_id, set_sign_task_run_id
from backend.services.sign_task_log_handler import TaskLogHandler
from backend.services.sign_task_runtime_contract import (
    WorkerExecutionPlan,
    build_runtime_config_snapshot,
    build_worker_execution_plan,
    build_worker_execution_snapshot,
)
from backend.services.sign_task_results import (
    task_already_running_result as build_task_already_running_result,
)
from backend.services.sign_task_run_summary import build_run_summary
from backend.services.task_flow_logger import TaskFlowLogger
from backend.utils.account_locks import get_account_lock
from backend.utils.proxy import build_proxy_dict
from backend.utils.tg_session import (
    get_account_proxy,
    get_account_session_string,
    get_global_semaphore,
)
from tg_signer_contracts.errors import BusinessRetryableError
from tg_signer_contracts.wait_budget import action_wait_budget

settings = get_settings()
BackendUserSigner = None
close_client_by_name = None


class TaskRunTimeoutError(TimeoutError):
    """Raised when the worker-level task run budget is exhausted."""


class AccountLockWaitTimeoutError(TimeoutError):
    """Raised when an account execution lock cannot be acquired in time."""


class GlobalConcurrencyWaitTimeoutError(TimeoutError):
    """Raised when the global execution semaphore cannot be acquired in time."""


def get_backend_user_signer_class():
    global BackendUserSigner
    if BackendUserSigner is None:
        from backend.services.sign_task_runtime import BackendUserSigner as runtime_signer

        BackendUserSigner = runtime_signer
    return BackendUserSigner


def get_close_client_by_name():
    global close_client_by_name
    if close_client_by_name is None:
        from tg_signer.client_manager import close_client_by_name as close_client

        close_client_by_name = close_client
    return close_client_by_name


class SignTaskExecutor:
    def __init__(
        self,
        *,
        workdir,
        active_logs: Dict[tuple[str, str], List[str]],
        active_log_offsets: Dict[tuple[str, str], int],
        active_tasks: Dict[tuple[str, str], bool],
        cleanup_tasks: Dict[tuple[str, str], asyncio.Task],
        account_locks: Dict[str, asyncio.Lock],
        account_last_run_end: Dict[str, float],
        account_cooldown_seconds: int,
        get_task,
        save_run_info,
    ):
        self.workdir = workdir
        self._active_logs = active_logs
        self._active_log_offsets = active_log_offsets
        self._active_tasks = active_tasks
        self._cleanup_tasks = cleanup_tasks
        self._account_locks = account_locks
        self._account_last_run_end = account_last_run_end
        self._account_cooldown_seconds = account_cooldown_seconds
        self._get_task = get_task
        self._save_run_info = save_run_info

    @staticmethod
    def task_requires_updates(task_config: Dict[str, Any] | None) -> bool:
        return True

    @staticmethod
    def _read_int_env(name: str, default: int, minimum: int = 0) -> int:
        try:
            return max(int(os.getenv(name, default) or default), minimum)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _read_float_env(name: str, default: float, minimum: float = 0.0) -> float:
        try:
            return max(float(os.getenv(name, default) or default), minimum)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _optional_float(value: Any, *, minimum: float = 0.0) -> float | None:
        if isinstance(value, bool) or value in (None, ""):
            return None
        try:
            return max(float(value), minimum)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_int(value: Any, *, minimum: int = 0) -> int | None:
        if isinstance(value, bool) or value in (None, ""):
            return None
        try:
            return max(int(value), minimum)
        except (TypeError, ValueError):
            return None

    @classmethod
    def client_cleanup_timeout_seconds(cls) -> float:
        return cls._read_float_env("SIGN_TASK_CLIENT_CLEANUP_TIMEOUT", 15.0, minimum=1.0)

    @classmethod
    def task_run_late_result_grace_seconds(cls) -> float:
        return cls._read_float_env("SIGN_TASK_RUN_LATE_RESULT_GRACE", 0.05, minimum=0.0)

    @classmethod
    def client_cleanup_late_result_grace_seconds(cls) -> float:
        return cls._read_float_env("SIGN_TASK_CLIENT_CLEANUP_LATE_RESULT_GRACE", 0.05, minimum=0.0)

    @classmethod
    def account_lock_wait_timeout_seconds(cls) -> float:
        return cls._read_float_env("SIGN_TASK_ACCOUNT_LOCK_TIMEOUT", 300.0, minimum=1.0)

    @classmethod
    def global_concurrency_wait_timeout_seconds(cls) -> float:
        return cls._read_float_env("SIGN_TASK_GLOBAL_CONCURRENCY_TIMEOUT", 300.0, minimum=1.0)

    async def _close_client_with_timeout(
        self,
        account_name: str,
        *,
        workdir: str,
        timeout_seconds: float,
        flow_logger: TaskFlowLogger,
        attempt: int,
        total_attempts: int,
        success: bool,
    ) -> Dict[str, Any]:
        cleanup_task = asyncio.create_task(
            get_close_client_by_name()(account_name, workdir=workdir)
        )
        done, _pending = await asyncio.wait({cleanup_task}, timeout=timeout_seconds)
        if cleanup_task in done:
            result = await cleanup_task
            return result if isinstance(result, dict) else {}

        cleanup_task.cancel()

        def consume_cleanup_result(task: asyncio.Task) -> None:
            base_meta = {
                "operation": "close_client_by_name",
                "timeout_scope": "client_cleanup",
                "timeout_seconds": timeout_seconds,
                "attempt": attempt,
                "total_attempts": total_attempts,
                "success": success,
            }
            try:
                task.result()
            except asyncio.CancelledError:
                flow_logger.append(
                    "Telegram client 清理超时后台任务已取消",
                    level="info",
                    stage="session",
                    event="client_cleanup_late_cancelled",
                    visible=False,
                    meta=base_meta,
                )
                pass
            except Exception as exc:
                flow_logger.append(
                    f"Telegram client 清理超时后台任务晚到异常: {exc}",
                    level="warning",
                    stage="session",
                    event="client_cleanup_late_exception",
                    meta={**base_meta, "error_type": type(exc).__name__},
                )
                logging.getLogger("backend").warning(
                    "后台 Telegram client 清理任务结束时仍失败: %s", exc
                )
            else:
                flow_logger.append(
                    "Telegram client 清理超时后台任务晚到完成",
                    level="info",
                    stage="session",
                    event="client_cleanup_late_completed",
                    visible=False,
                    meta=base_meta,
                )

        cleanup_task.add_done_callback(consume_cleanup_result)
        late_result_grace = self.client_cleanup_late_result_grace_seconds()
        if late_result_grace > 0:
            await asyncio.wait({cleanup_task}, timeout=late_result_grace)
            await asyncio.sleep(0)
        raise TimeoutError(f"client cleanup timed out after {timeout_seconds}s")

    async def _run_signer_once_with_timeout(
        self,
        signer,
        *,
        timeout_seconds: int,
        flow_logger: TaskFlowLogger,
        task_attempt: int,
        total_attempts: int,
    ) -> None:
        run_task = asyncio.create_task(signer.run_once(num_of_dialogs=0))
        done, _pending = await asyncio.wait({run_task}, timeout=timeout_seconds)
        if run_task in done:
            await run_task
            return

        run_task.cancel()

        def consume_run_result(task: asyncio.Task) -> None:
            base_meta = {
                "operation": "signer.run_once",
                "timeout_scope": "outer_task",
                "timeout_seconds": timeout_seconds,
                "attempt": task_attempt,
                "total_attempts": total_attempts,
            }
            try:
                task.result()
            except asyncio.CancelledError:
                flow_logger.append(
                    "Worker 总超时后台任务已取消",
                    level="info",
                    stage="task",
                    event="task_run_late_cancelled",
                    visible=False,
                    meta=base_meta,
                )
                pass
            except Exception as exc:
                flow_logger.append(
                    f"Worker 总超时后台任务晚到异常: {exc}",
                    level="warning",
                    stage="task",
                    event="task_run_late_exception",
                    meta={**base_meta, "error_type": type(exc).__name__},
                )
                logging.getLogger("backend").warning(
                    "后台任务总超时后 signer.run_once 仍失败: %s", exc
                )
            else:
                flow_logger.append(
                    "Worker 总超时后台任务晚到完成",
                    level="info",
                    stage="task",
                    event="task_run_late_completed",
                    visible=False,
                    meta=base_meta,
                )

        run_task.add_done_callback(consume_run_result)
        flow_logger.append(
            f"Worker 单次执行达到总超时预算: {timeout_seconds} 秒",
            level="error",
            stage="task",
            event="task_run_timeout",
            meta={
                "operation": "signer.run_once",
                "timeout_scope": "outer_task",
                "timeout_seconds": timeout_seconds,
                "attempt": task_attempt,
                "total_attempts": total_attempts,
                "run_task_cancelled": True,
                "cleanup_expected": True,
            },
        )
        late_result_grace = self.task_run_late_result_grace_seconds()
        if late_result_grace > 0:
            await asyncio.wait({run_task}, timeout=late_result_grace)
            await asyncio.sleep(0)
        raise TaskRunTimeoutError(f"task run timed out after {timeout_seconds}s")

    @classmethod
    def task_timeout_seconds(cls, task_config: Dict[str, Any] | None) -> int:
        configured_timeout = cls._read_int_env("SIGN_TASK_RUN_TIMEOUT", 180, minimum=30)
        if not isinstance(task_config, dict):
            return configured_timeout

        chats = task_config.get("chats")
        if not isinstance(chats, list) or not chats:
            return configured_timeout

        default_event_timeout = cls._read_float_env("TG_EVENT_ENGINE_TIMEOUT", 120.0, minimum=1.0)
        default_inline_retries = int(cls._read_float_env("TG_EVENT_ENGINE_INLINE_RETRIES", 3, minimum=0))
        event_budget = 0.0
        for chat in chats:
            if not isinstance(chat, dict):
                event_budget += default_event_timeout
                continue
            event_timeout = cls._optional_float(
                chat.get("event_timeout"),
                minimum=1.0,
            )
            event_budget += event_timeout if event_timeout is not None else default_event_timeout
            inline_retries = cls._optional_int(chat.get("event_retries"), minimum=0)
            actions = chat.get("actions")
            if isinstance(actions, list):
                event_budget += action_wait_budget(
                    actions,
                    default_inline_retries if inline_retries is None else inline_retries,
                )

        sign_interval = cls._optional_float(
            task_config.get("sign_interval"),
            minimum=0.0,
        ) or 0.0
        if len(chats) > 1:
            event_budget += sign_interval * (len(chats) - 1)

        overhead = cls._read_int_env("SIGN_TASK_RUN_TIMEOUT_OVERHEAD", 90, minimum=30)
        return max(configured_timeout, int(event_budget + overhead))

    @classmethod
    def task_runtime_config_meta(cls, task_config: Dict[str, Any] | None) -> Dict[str, Any]:
        return build_runtime_config_snapshot(task_config)

    @classmethod
    def worker_execution_meta(
        cls,
        task_config: Dict[str, Any] | None,
        *,
        requires_updates: bool,
        retry_count: int,
        task_timeout_seconds: int | None,
        session_retry_count: int,
    ) -> Dict[str, Any]:
        return build_worker_execution_snapshot(
            task_config,
            requires_updates=requires_updates,
            retry_count=retry_count,
            task_timeout_seconds=task_timeout_seconds,
            session_retry_count=session_retry_count,
        )

    @classmethod
    def worker_execution_plan(
        cls,
        task_config: Dict[str, Any] | None,
        *,
        requires_updates: bool,
        retry_count: int,
        session_retry_count: int,
    ) -> WorkerExecutionPlan:
        task_timeout_seconds = cls.task_timeout_seconds(task_config)
        return build_worker_execution_plan(
            task_config,
            requires_updates=requires_updates,
            retry_count=retry_count,
            task_timeout_seconds=task_timeout_seconds,
            session_retry_count=session_retry_count,
        )

    @staticmethod
    def _extract_last_reply(final_logs: List[str]) -> str:
        last_reply = ""
        for line in reversed(final_logs):
            if "收到来自「" not in line or (
                "」的消息:" not in line and "」对消息的更新，消息:" not in line
            ):
                continue
            try:
                splitter = "」的消息:" if "」的消息:" in line else "」对消息的更新，消息:"
                reply_part = line.split(splitter, 1)[-1].strip()
                if reply_part.startswith("Message:"):
                    reply_part = reply_part[len("Message:") :].strip()

                if "text: " in reply_part:
                    text_content = reply_part.split("text: ", 1)[-1].split("\n")[0].strip()
                    if text_content:
                        last_reply = text_content
                    elif "图片: " in reply_part:
                        last_reply = "[图片] " + reply_part.split("图片: ", 1)[-1].split("\n")[0].strip()
                    else:
                        last_reply = reply_part.replace("\n", " ").strip()
                else:
                    last_reply = reply_part.replace("\n", " ").strip()

                if len(last_reply) > 200:
                    last_reply = last_reply[:197] + "..."
            except Exception:
                pass
            if last_reply:
                break
        return last_reply

    @staticmethod
    def _failure_meta(
        exc: Exception,
        *,
        task_attempt: int,
        total_attempts: int,
        retryable: bool,
        timeout_seconds: int | None,
    ) -> Dict[str, Any]:
        bounded_timeout_errors = (
            TaskRunTimeoutError,
            AccountLockWaitTimeoutError,
            GlobalConcurrencyWaitTimeoutError,
        )
        error_type = "TimeoutError" if isinstance(exc, bounded_timeout_errors) else type(exc).__name__
        meta: Dict[str, Any] = {
            "error_type": error_type,
            "retryable": retryable,
            "attempt": task_attempt,
            "total_attempts": total_attempts,
        }
        if isinstance(exc, TaskRunTimeoutError):
            meta["timeout_scope"] = "outer_task"
        elif isinstance(exc, AccountLockWaitTimeoutError):
            meta["timeout_scope"] = "account_lock"
        elif isinstance(exc, GlobalConcurrencyWaitTimeoutError):
            meta["timeout_scope"] = "global_concurrency"
        elif isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
            meta["timeout_scope"] = "internal_rpc"
        else:
            meta["timeout_scope"] = "none"
        if timeout_seconds is not None:
            meta["timeout_seconds"] = timeout_seconds
        return meta

    @staticmethod
    def task_already_running_result() -> Dict[str, Any]:
        return build_task_already_running_result()

    async def run_task_with_logs(self, account_name: str, task_name: str) -> Dict[str, Any]:
        task_key = (account_name, task_name)
        if self._active_tasks.get(task_key, False):
            return self.task_already_running_result()

        if account_name not in self._account_locks:
            self._account_locks[account_name] = get_account_lock(account_name)
        account_lock = self._account_locks[account_name]

        self._active_tasks[task_key] = True
        self._active_logs[task_key] = []
        self._active_log_offsets[task_key] = 0
        task_run_id = uuid.uuid4().hex
        active_log_offset_ref = {"value": 0}
        flow_items: List[Dict[str, Any]] = []
        flow_logger = TaskFlowLogger(
            self._active_logs[task_key],
            flow_items,
            active_log_offset_ref,
        )

        tg_logger = logging.getLogger("tg-signer")
        previous_tg_logger_level = tg_logger.level
        should_restore_tg_logger_level = False
        if tg_logger.getEffectiveLevel() > logging.INFO:
            tg_logger.setLevel(logging.INFO)
            should_restore_tg_logger_level = True
        log_handler = TaskLogHandler(
            self._active_logs[task_key],
            flow_items,
            active_log_offset_ref,
            run_id=task_run_id,
        )
        log_handler.setLevel(logging.INFO)
        tg_logger.addHandler(log_handler)

        success = False
        error_msg = ""
        output_str = ""
        signer = None
        configured_retry_count = 0
        total_attempts = 1
        current_task_attempt = 0
        task_timeout_seconds: int | None = None
        account_lock_acquired = False
        run_summary: Dict[str, Any] = {}
        log_context_token = None

        try:
            lock_wait_started_at = time.perf_counter()
            account_lock_timeout_seconds = self.account_lock_wait_timeout_seconds()
            if account_lock.locked():
                flow_logger.append(
                    "等待账号执行锁",
                    level="info",
                    stage="task",
                    event="account_lock_wait_started",
                    meta={
                        "operation": "account_lock.acquire",
                        "timeout_scope": "account_lock",
                        "locked": True,
                        "timeout_seconds": account_lock_timeout_seconds,
                    },
                )
            try:
                await asyncio.wait_for(
                    account_lock.acquire(),
                    timeout=account_lock_timeout_seconds,
                )
            except asyncio.TimeoutError:
                wait_seconds = time.perf_counter() - lock_wait_started_at
                flow_logger.append(
                    f"等待账号执行锁超时: {account_lock_timeout_seconds} 秒",
                    level="error",
                    stage="task",
                    event="account_lock_wait_timeout",
                    meta={
                        "operation": "account_lock.acquire",
                        "timeout_scope": "account_lock",
                        "wait_seconds": round(wait_seconds, 3),
                        "timeout_seconds": account_lock_timeout_seconds,
                    },
                )
                raise AccountLockWaitTimeoutError(
                    f"account lock wait timed out after {account_lock_timeout_seconds}s"
                )
            account_lock_acquired = True
            log_context_token = set_sign_task_run_id(task_run_id)
            lock_wait_seconds = time.perf_counter() - lock_wait_started_at
            flow_logger.append(
                "账号执行锁已获取",
                level="info",
                stage="task",
                event="account_lock_acquired",
                visible=lock_wait_seconds > 0.5,
                meta={
                    "operation": "account_lock.acquire",
                    "timeout_scope": "account_lock",
                    "wait_seconds": round(lock_wait_seconds, 3),
                    "timeout_seconds": account_lock_timeout_seconds,
                },
            )

            last_end = self._account_last_run_end.get(account_name)
            if last_end:
                gap = time.time() - last_end
                wait_seconds = self._account_cooldown_seconds - gap
                if wait_seconds > 0:
                    flow_logger.append(
                        f"等待账号冷却 {int(wait_seconds)} 秒",
                        level="info",
                        stage="task",
                        event="cooldown_wait",
                        meta={"wait_seconds": int(wait_seconds)},
                    )
                    await asyncio.sleep(wait_seconds)

            flow_logger.append(
                f"开始执行任务: {task_name} (账号: {account_name})",
                level="info",
                stage="task",
                event="task_started",
                meta={"task_name": task_name, "account_name": account_name},
            )

            from backend.services.config import get_config_service

            config_service = get_config_service()
            tg_config = config_service.get_telegram_config()
            api_id = os.getenv("TG_API_ID") or tg_config.get("api_id")
            api_hash = os.getenv("TG_API_HASH") or tg_config.get("api_hash")

            try:
                api_id = int(api_id) if api_id is not None else None
            except (TypeError, ValueError):
                api_id = None

            if isinstance(api_hash, str):
                api_hash = api_hash.strip()

            if not api_id or not api_hash:
                raise ValueError("未配置 Telegram API ID 或 API Hash")

            session_dir = settings.resolve_session_dir()
            session_string = get_account_session_string(account_name)
            if not session_string:
                raise ValueError(f"账号 {account_name} 的 session_string 不存在")

            proxy_dict = None
            proxy_value = get_account_proxy(account_name)
            if proxy_value:
                proxy_dict = build_proxy_dict(proxy_value)

            task_cfg = self._get_task(task_name, account_name=account_name)
            disable_sign_task_updates = (
                (os.getenv("TG_SIGN_TASK_DISABLE_UPDATES") or "").strip().lower()
                in {"1", "true", "yes", "on"}
            )
            requires_updates = (
                self.task_requires_updates(task_cfg)
                and not disable_sign_task_updates
            )
            if isinstance(task_cfg, dict):
                configured_retry_count = (
                    self._optional_int(task_cfg.get("retry_count"), minimum=0) or 0
                )
            max_session_retries = 3
            worker_plan = self.worker_execution_plan(
                task_cfg,
                requires_updates=requires_updates,
                retry_count=configured_retry_count,
                session_retry_count=max_session_retries,
            )
            runtime_meta = worker_plan.runtime_meta
            flow_logger.append(
                f"运行配置: engine={runtime_meta.get('engine')} chats={runtime_meta.get('chat_count')}",
                level="info",
                stage="task",
                event="task_runtime_config",
                meta=runtime_meta,
            )
            flow_logger.append(
                f"消息更新监听: {'开启' if requires_updates else '关闭'}",
                level="info",
                stage="session",
                event="updates_mode",
                visible=False,
                meta={"requires_updates": requires_updates},
            )
            flow_logger.append(
                f"失败重试次数: {configured_retry_count}",
                level="info",
                stage="task",
                event="task_retry_config",
                visible=configured_retry_count > 0,
                meta={
                    "retry_count": configured_retry_count,
                    "total_attempts": worker_plan.total_attempts,
                    "retry_budget_remaining": configured_retry_count,
                },
            )

            signer = get_backend_user_signer_class()(
                task_name=task_name,
                session_dir=str(session_dir),
                account=account_name,
                workdir=self.workdir,
                proxy=proxy_dict,
                session_string=session_string,
                in_memory=True,
                api_id=api_id,
                api_hash=api_hash,
                no_updates=worker_plan.no_updates,
                log_run_id=task_run_id,
            )

            task_timeout_seconds = worker_plan.task_timeout_seconds
            flow_logger.append(
                f"单次执行总超时: {task_timeout_seconds} 秒",
                level="info",
                stage="task",
                event="task_timeout_config",
                visible=False,
                meta={"timeout_seconds": task_timeout_seconds},
            )

            global_semaphore = get_global_semaphore()
            global_semaphore_acquired = False
            global_wait_started_at = time.perf_counter()
            global_concurrency_timeout_seconds = self.global_concurrency_wait_timeout_seconds()
            if global_semaphore.locked():
                flow_logger.append(
                    "等待全局执行并发槽",
                    level="info",
                    stage="task",
                    event="global_concurrency_wait_started",
                    meta={
                        "operation": "global_concurrency.acquire",
                        "timeout_scope": "global_concurrency",
                        "locked": True,
                        "timeout_seconds": global_concurrency_timeout_seconds,
                    },
                )
            try:
                await asyncio.wait_for(
                    global_semaphore.acquire(),
                    timeout=global_concurrency_timeout_seconds,
                )
            except asyncio.TimeoutError:
                wait_seconds = time.perf_counter() - global_wait_started_at
                flow_logger.append(
                    f"等待全局执行并发槽超时: {global_concurrency_timeout_seconds} 秒",
                    level="error",
                    stage="task",
                    event="global_concurrency_wait_timeout",
                    meta={
                        "operation": "global_concurrency.acquire",
                        "timeout_scope": "global_concurrency",
                        "wait_seconds": round(wait_seconds, 3),
                        "timeout_seconds": global_concurrency_timeout_seconds,
                    },
                )
                raise GlobalConcurrencyWaitTimeoutError(
                    "global concurrency wait timed out after "
                    f"{global_concurrency_timeout_seconds}s"
                )
            global_semaphore_acquired = True
            global_wait_seconds = time.perf_counter() - global_wait_started_at
            flow_logger.append(
                "全局执行并发槽已获取",
                level="info",
                stage="task",
                event="global_concurrency_acquired",
                visible=global_wait_seconds > 0.5,
                meta={
                    "operation": "global_concurrency.acquire",
                    "timeout_scope": "global_concurrency",
                    "wait_seconds": round(global_wait_seconds, 3),
                    "timeout_seconds": global_concurrency_timeout_seconds,
                },
            )
            try:
                max_session_retries = worker_plan.session_retry_count
                total_attempts = worker_plan.total_attempts
                worker_meta = worker_plan.worker_meta
                flow_logger.append(
                    "Worker 执行契约: "
                    f"attempts={worker_meta.get('total_attempts')} "
                    f"timeout={worker_meta.get('task_timeout_seconds')}s "
                    f"updates={'on' if worker_meta.get('requires_updates') else 'off'}",
                    level="info",
                    stage="task",
                    event="worker_execution_contract",
                    visible=False,
                    meta=worker_meta,
                )
                last_exception = None
                for task_attempt in range(1, total_attempts + 1):
                    current_task_attempt = task_attempt
                    if task_attempt > 1:
                        flow_logger.append(
                            f"开始第 {task_attempt}/{total_attempts} 次重试",
                            level="warning",
                            stage="task",
                            event="task_retry_started",
                            meta={
                                "attempt": task_attempt,
                                "total_attempts": total_attempts,
                                "retry_count": configured_retry_count,
                                "retry_budget_remaining": max(total_attempts - task_attempt, 0),
                            },
                        )
                    try:
                        for attempt in range(max_session_retries):
                            try:
                                await self._run_signer_once_with_timeout(
                                    signer,
                                    timeout_seconds=task_timeout_seconds,
                                    flow_logger=flow_logger,
                                    task_attempt=task_attempt,
                                    total_attempts=total_attempts,
                                )
                                last_exception = None
                                break
                            except Exception as e:
                                if "database is locked" in str(e).lower() and attempt < max_session_retries - 1:
                                    delay = (attempt + 1) * 3
                                    flow_logger.append(
                                        f"Session 被锁定，{delay} 秒后重试...",
                                        level="warning",
                                        stage="session",
                                        event="session_retry",
                                        meta={"retry_delay_seconds": delay, "attempt": attempt + 1},
                                    )
                                    await asyncio.sleep(delay)
                                    continue
                                raise
                        if last_exception is None:
                            break
                    except Exception as e:
                        last_exception = e
                        is_retryable_business_error = isinstance(e, BusinessRetryableError)
                        if not is_retryable_business_error or task_attempt >= total_attempts:
                            raise
                        flow_logger.append(
                            f"业务失败，准备重试: {e}",
                            level="warning",
                            stage="task",
                            event="task_retry_scheduled",
                            meta={
                                "attempt": task_attempt,
                                "total_attempts": total_attempts,
                                "retry_count": configured_retry_count,
                                "retry_budget_remaining": max(
                                    total_attempts - task_attempt - 1,
                                    0,
                                ),
                                "error": str(e),
                                "error_type": type(e).__name__,
                                "retryable": True,
                            },
                        )
                        await asyncio.sleep(2)
                        continue
                success = True
            finally:
                if global_semaphore_acquired:
                    global_semaphore.release()
                    flow_logger.append(
                        "全局执行并发槽已释放",
                        level="info",
                        stage="task",
                        event="global_concurrency_released",
                        visible=False,
                        meta={
                            "operation": "global_concurrency.release",
                            "timeout_scope": "global_concurrency",
                            "success": success,
                            "attempt": current_task_attempt,
                            "total_attempts": total_attempts,
                        },
                    )

            flow_logger.append(
                "任务执行完成",
                level="success",
                stage="result",
                event="task_completed",
                meta={
                    "task_name": task_name,
                    "account_name": account_name,
                    "attempt": current_task_attempt,
                    "total_attempts": total_attempts,
                },
            )
            await asyncio.sleep(2)
        except Exception as e:
            error_detail = str(e) or type(e).__name__
            error_msg = f"任务执行出错: {error_detail}"
            is_retryable_business_error = isinstance(e, BusinessRetryableError)
            flow_logger.append(
                error_msg,
                level="error",
                stage="result",
                event="task_failed",
                meta={
                    "task_name": task_name,
                    "account_name": account_name,
                    **self._failure_meta(
                        e,
                        task_attempt=current_task_attempt,
                        total_attempts=total_attempts,
                        retryable=is_retryable_business_error,
                        timeout_seconds=task_timeout_seconds,
                    ),
                },
            )
            traceback.print_exc()
            logging.getLogger("backend").error(error_msg)
        finally:
            cleanup_deferred_cancelled = False
            self._active_log_offsets[task_key] = active_log_offset_ref["value"]
            self._account_last_run_end[account_name] = time.time()
            if signer is not None:
                cleanup_timeout_seconds = self.client_cleanup_timeout_seconds()
                cleanup_meta = {
                    "operation": "close_client_by_name",
                    "timeout_scope": "client_cleanup",
                    "attempt": current_task_attempt,
                    "total_attempts": total_attempts,
                    "success": success,
                    "timeout_seconds": cleanup_timeout_seconds,
                }
                flow_logger.append(
                    "开始清理 Telegram client",
                    level="info",
                    stage="session",
                    event="client_cleanup_started",
                    visible=False,
                    meta=cleanup_meta,
                )
                cleanup_task = asyncio.create_task(
                    self._close_client_with_timeout(
                        account_name,
                        workdir=signer._session_dir,
                        timeout_seconds=cleanup_timeout_seconds,
                        flow_logger=flow_logger,
                        attempt=current_task_attempt,
                        total_attempts=total_attempts,
                        success=success,
                    )
                )
                try:
                    try:
                        cleanup_report = await asyncio.shield(cleanup_task)
                    except asyncio.CancelledError:
                        cleanup_deferred_cancelled = True
                        flow_logger.append(
                            "任务取消请求已延后到 Telegram client 清理后处理",
                            level="warning",
                            stage="session",
                            event="task_cancellation_deferred_for_cleanup",
                            meta=cleanup_meta,
                        )
                        cleanup_report = await cleanup_task
                    flow_logger.append(
                        "Telegram client 清理完成",
                        level="info",
                        stage="session",
                        event="client_cleanup_completed",
                        visible=False,
                        meta={**cleanup_meta, **cleanup_report},
                    )
                except Exception as cleanup_exc:
                    flow_logger.append(
                        f"Telegram client 清理失败: {cleanup_exc}",
                        level="warning",
                        stage="session",
                        event="client_cleanup_failed",
                        meta={
                            **cleanup_meta,
                            "error_type": type(cleanup_exc).__name__,
                        },
                    )
                    logging.getLogger("backend").warning(
                        "清理 Telegram client 失败: %s", cleanup_exc
                    )
            if account_lock_acquired:
                account_lock.release()
                account_lock_acquired = False
                flow_logger.append(
                    "账号执行锁已释放",
                    level="info",
                    stage="task",
                    event="account_lock_released",
                    visible=False,
                    meta={
                        "operation": "account_lock.release",
                        "timeout_scope": "account_lock",
                        "success": success,
                        "attempt": current_task_attempt,
                        "total_attempts": total_attempts,
                    },
                )
            if log_context_token is not None:
                reset_sign_task_run_id(log_context_token)
                log_context_token = None
            tg_logger.removeHandler(log_handler)
            if should_restore_tg_logger_level:
                tg_logger.setLevel(previous_tg_logger_level)

            final_logs = list(self._active_logs.get(task_key, []))
            output_str = "\n".join(final_logs)
            msg = error_msg if not success else self._extract_last_reply(final_logs)
            run_summary = build_run_summary(
                flow_items,
                success=success,
                error=error_msg,
            )
            try:
                self._save_run_info(
                    task_name,
                    success,
                    msg,
                    account_name,
                    flow_logs=final_logs,
                    flow_items=flow_items,
                    run_summary=run_summary,
                )
            except Exception as save_exc:
                flow_logger.append(
                    f"运行记录保存失败: {save_exc}",
                    level="warning",
                    stage="result",
                    event="task_run_info_save_failed",
                    meta={
                        "error_type": type(save_exc).__name__,
                        "success": success,
                        "attempt": current_task_attempt,
                        "total_attempts": total_attempts,
                    },
                )
                logging.getLogger("backend").warning(
                    "保存签到任务运行记录失败: %s", save_exc, exc_info=True
                )
                final_logs = list(self._active_logs.get(task_key, []))
                output_str = "\n".join(final_logs)
                run_summary = build_run_summary(
                    flow_items,
                    success=success,
                    error=error_msg,
                )

            self._active_tasks[task_key] = False
            self._active_logs.pop(task_key, None)
            self._active_log_offsets.pop(task_key, None)

            old_cleanup_task = self._cleanup_tasks.get(task_key)
            if old_cleanup_task and not old_cleanup_task.done():
                old_cleanup_task.cancel()
            self._cleanup_tasks.pop(task_key, None)
            if cleanup_deferred_cancelled:
                raise asyncio.CancelledError

        return {
            "success": success,
            "output": output_str,
            "error": error_msg,
            "run_summary": run_summary,
            "started": True,
            "code": "",
        }
