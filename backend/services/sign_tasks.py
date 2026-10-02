"""
签到任务服务层
提供签到任务的 CRUD 操作和执行功能
"""

from __future__ import annotations

import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
from typing import Any, Dict, List, Optional

from backend.core.config import get_settings
from backend.services.sign_task_history import SignTaskHistoryService
from backend.services.sign_task_management import SignTaskManagementService
from backend.services.sign_task_results import task_already_running_result

settings = get_settings()


class SignTaskService:
    """签到任务服务类"""

    @staticmethod
    def _read_positive_int_env(name: str, default: int, minimum: int = 1) -> int:
        raw = os.getenv(name)
        if raw is None:
            return default
        try:
            return max(int(raw), minimum)
        except (TypeError, ValueError):
            return default

    def __init__(self):
        from backend.core.config import get_settings
        from backend.repositories.sign_task_config_repo import get_sign_task_config_repo
        from backend.repositories.sign_task_history_repo import get_sign_task_history_repo

        settings = get_settings()
        self.workdir = settings.resolve_workdir()
        self.signs_dir = self.workdir / "signs"
        self.signs_dir.mkdir(parents=True, exist_ok=True)
        self._config_repo = get_sign_task_config_repo()
        self._history_repo = get_sign_task_history_repo()
        self._active_logs: Dict[tuple[str, str], List[str]] = {}  # (account, task) -> logs
        self._active_log_offsets: Dict[tuple[str, str], int] = {}  # (account, task) -> dropped count
        self._active_tasks: Dict[tuple[str, str], bool] = {}  # (account, task) -> running
        self._starting_tasks: set[tuple[str, str]] = set()
        self._cleanup_tasks: Dict[tuple[str, str], asyncio.Task] = {}
        self._account_locks: Dict[str, asyncio.Lock] = {}  # 账号锁
        self._account_last_run_end: Dict[str, float] = {}  # 账号最后一次结束时间
        self._account_cooldown_seconds = int(
            os.getenv("SIGN_TASK_ACCOUNT_COOLDOWN", "5")
        )
        self._history_max_entries = self._read_positive_int_env(
            "SIGN_TASK_HISTORY_MAX_ENTRIES", 100, 10
        )
        self._history_max_flow_lines = self._read_positive_int_env(
            "SIGN_TASK_HISTORY_MAX_FLOW_LINES", 200, 20
        )
        self._history_max_line_chars = self._read_positive_int_env(
            "SIGN_TASK_HISTORY_MAX_LINE_CHARS", 500, 80
        )
        self._history_service = SignTaskHistoryService(
            self._history_repo,
            self._config_repo,
            history_max_entries=self._history_max_entries,
            history_max_flow_lines=self._history_max_flow_lines,
            history_max_line_chars=self._history_max_line_chars,
        )
        self._management_service = SignTaskManagementService(
            self._config_repo,
            get_now=self._now,
            append_scheduler_log=self._append_scheduler_log,
        )
        self._chat_cache_service = None
        self._executor = None

    @property
    def chat_cache_service(self):
        if self._chat_cache_service is None:
            from backend.services.sign_task_chat_cache import SignTaskChatCacheService

            self._chat_cache_service = SignTaskChatCacheService(
                self.signs_dir,
                self._account_locks,
            )
        return self._chat_cache_service

    @property
    def executor(self):
        if self._executor is None:
            from backend.services.sign_task_executor import SignTaskExecutor

            self._executor = SignTaskExecutor(
                workdir=self.workdir,
                active_logs=self._active_logs,
                active_log_offsets=self._active_log_offsets,
                active_tasks=self._active_tasks,
                cleanup_tasks=self._cleanup_tasks,
                account_locks=self._account_locks,
                account_last_run_end=self._account_last_run_end,
                account_cooldown_seconds=self._account_cooldown_seconds,
                get_task=self._get_task_config,
                save_run_info=self._save_run_info,
            )
        return self._executor

    def get_task_history_logs(
        self, task_name: str, account_name: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        return self._history_service.get_task_history_logs(
            task_name=task_name,
            account_name=account_name,
            limit=limit,
        )

    def get_account_history_logs(self, account_name: str, limit: int | None = None) -> List[Dict[str, Any]]:
        """获取某账号下所有任务的最近历史日志"""
        return self._history_service.get_account_history_logs(account_name, limit=limit)

    def clear_account_history_logs(self, account_name: str) -> Dict[str, int]:
        """清理某账号的历史日志，不影响其他账号"""
        tasks = self.list_tasks(account_name=account_name)
        return self._history_service.clear_account_history_logs(account_name, tasks)

    def _get_last_run_info_by_name(
        self, task_name: str, account_name: str = ""
    ) -> Optional[Dict[str, Any]]:
        """通过任务名获取最后执行信息"""
        return self._history_service.get_last_run_info(task_name, account_name)

    def _save_run_info(
        self,
        task_name: str,
        success: bool,
        message: str = "",
        account_name: str = "",
        flow_logs: Optional[List[str]] = None,
        flow_items: Optional[List[Dict[str, Any]]] = None,
        run_summary: Optional[Dict[str, Any]] = None,
    ):
        """保存任务执行历史"""
        self._history_service.save_run_info(
            task_name=task_name,
            success=success,
            message=message,
            account_name=account_name,
            flow_logs=flow_logs,
            flow_items=flow_items,
            run_summary=run_summary,
        )

    def _now(self):
        return self._history_service._now()

    def _append_scheduler_log(self, filename: str, message: str) -> None:
        try:
            logs_dir = settings.resolve_logs_dir()
            logs_dir.mkdir(parents=True, exist_ok=True)
            log_path = logs_dir / filename
            log = logging.getLogger(f"backend.scheduler.file.{filename}")
            if not log.handlers:
                log.addHandler(RotatingFileHandler(log_path, maxBytes=3 * 1024 * 1024, backupCount=3, encoding="utf-8"))
                log.setLevel(logging.INFO)
                log.propagate = False
            log.info(message)
        except Exception as e:
            logging.getLogger('backend.sign_tasks').warning(
                'Failed to write scheduler log %s: %s', filename, e
            )

    def list_tasks(self, account_name: Optional[str] = None) -> List[Dict[str, Any]]:
        return self._management_service.list_tasks(
            self._history_repo.get_latest_summaries, account_name=account_name,
        )

    def list_task_configs(self, account_name: Optional[str] = None) -> List[Dict[str, Any]]:
        return self._config_repo.list_configs(account_name)

    def task_exists(self, task_name: str, account_name: str) -> bool:
        return self._config_repo.exists(task_name, account_name)

    def get_history_state(self, task_name: str, account_name: str) -> Dict[str, Any] | None:
        revision = self._config_repo.get_revision(task_name, account_name)
        if revision is None:
            return None
        marker = self._history_repo.get_history_marker(task_name, account_name, self._history_service.retention_cutoff())
        return {"revision": f"{revision}:{marker}", "running": self.is_task_running(task_name, account_name=account_name)}

    def prune_expired_history_logs(self) -> Dict[str, int]:
        return self._history_service.prune_expired_history_logs()

    def get_task(
        self, task_name: str, account_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        return self._management_service.get_task(
            task_name,
            account_name,
            self._get_last_run_info_by_name,
        )

    def _get_task_config(
        self, task_name: str, account_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        return self._management_service.get_task(task_name, account_name)

    def create_task(
        self,
        task_name: str,
        sign_at: str,
        chats: List[Dict[str, Any]],
        random_seconds: int = 0,
        sign_interval: Optional[int] = None,
        retry_count: int = 0,
        account_name: str = "",
        execution_mode: str = "fixed",
        range_start: str = "",
        range_end: str = "",
    ) -> Dict[str, Any]:
        return self._management_service.create_task(
            task_name=task_name,
            sign_at=sign_at,
            chats=chats,
            random_seconds=random_seconds,
            sign_interval=sign_interval,
            retry_count=retry_count,
            account_name=account_name,
            execution_mode=execution_mode,
            range_start=range_start,
            range_end=range_end,
        )

    async def create_task_and_sync(
        self,
        task_name: str,
        sign_at: str,
        chats: List[Dict[str, Any]],
        random_seconds: int = 0,
        sign_interval: Optional[int] = None,
        retry_count: int = 0,
        account_name: str = "",
        execution_mode: str = "fixed",
        range_start: str = "",
        range_end: str = "",
    ) -> Dict[str, Any]:
        return await self._management_service.create_task_and_sync(
            task_name=task_name,
            sign_at=sign_at,
            chats=chats,
            random_seconds=random_seconds,
            sign_interval=sign_interval,
            retry_count=retry_count,
            account_name=account_name,
            execution_mode=execution_mode,
            range_start=range_start,
            range_end=range_end,
        )

    def update_task(
        self,
        task_name: str,
        sign_at: Optional[str] = None,
        chats: Optional[List[Dict[str, Any]]] = None,
        random_seconds: Optional[int] = None,
        sign_interval: Optional[int] = None,
        retry_count: Optional[int] = None,
        account_name: Optional[str] = None,
        execution_mode: Optional[str] = None,
        range_start: Optional[str] = None,
        range_end: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._management_service.update_task(
            task_name=task_name,
            sign_at=sign_at,
            chats=chats,
            random_seconds=random_seconds,
            sign_interval=sign_interval,
            retry_count=retry_count,
            account_name=account_name,
            execution_mode=execution_mode,
            range_start=range_start,
            range_end=range_end,
        )

    async def update_task_and_sync(
        self,
        task_name: str,
        sign_at: Optional[str] = None,
        chats: Optional[List[Dict[str, Any]]] = None,
        random_seconds: Optional[int] = None,
        sign_interval: Optional[int] = None,
        retry_count: Optional[int] = None,
        account_name: Optional[str] = None,
        execution_mode: Optional[str] = None,
        range_start: Optional[str] = None,
        range_end: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await self._management_service.update_task_and_sync(
            task_name=task_name,
            sign_at=sign_at,
            chats=chats,
            random_seconds=random_seconds,
            sign_interval=sign_interval,
            retry_count=retry_count,
            account_name=account_name,
            execution_mode=execution_mode,
            range_start=range_start,
            range_end=range_end,
        )

    async def set_task_enabled_and_sync(
        self, task_name: str, account_name: str, enabled: bool
    ) -> Dict[str, Any]:
        return await self._management_service.set_task_enabled_and_sync(
            task_name=task_name,
            account_name=account_name,
            enabled=enabled,
        )

    def delete_task(self, task_name: str, account_name: Optional[str] = None) -> bool:
        return self._management_service.delete_task(task_name, account_name=account_name)

    async def delete_task_and_sync(
        self, task_name: str, account_name: Optional[str] = None
    ) -> bool:
        return await self._management_service.delete_task_and_sync(
            task_name,
            account_name=account_name,
        )

    async def get_account_chats(
        self,
        account_name: str,
        force_refresh: bool = False,
        *,
        auto_refresh_if_expired: bool = False,
        ensure_exists: bool = False,
        include_items: bool = True,
    ) -> Dict[str, Any]:
        return await self.chat_cache_service.get_account_chats(
            account_name,
            force_refresh=force_refresh,
            auto_refresh_if_expired=auto_refresh_if_expired,
            ensure_exists=ensure_exists,
            include_items=include_items,
        )

    def search_account_chats(
        self,
        account_name: str,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        return self.chat_cache_service.search_account_chats(
            account_name,
            query,
            limit=limit,
            offset=offset,
        )

    async def refresh_account_chats(self, account_name: str) -> List[Dict[str, Any]]:
        return await self.chat_cache_service.refresh_account_chats(account_name)

    def get_account_chat_cache(self, account_name: str) -> Dict[str, Any]:
        return self.chat_cache_service.get_account_chat_cache(account_name)

    def ensure_account_chat_cache_meta(self, account_name: str) -> Dict[str, Any]:
        return self.chat_cache_service.ensure_account_cache_meta(account_name)

    async def run_task(self, account_name: str, task_name: str) -> Dict[str, Any]:
        """
        运行签到任务 (兼容接口，内部调用 run_task_with_logs)
        """
        return await self.run_task_with_logs(account_name, task_name)

    async def start_task_in_background(
        self, account_name: str, task_name: str
    ) -> Dict[str, Any]:
        task = self._get_task_config(task_name, account_name=account_name)
        if not task:
            raise ValueError(f"任务 {task_name} 不存在")

        task_key = self._task_key(account_name, task_name)
        if self.is_task_running(task_name, account_name=account_name):
            return task_already_running_result()

        async def _run_in_background() -> None:
            try:
                await self.run_task_with_logs(account_name, task_name)
            except Exception:
                logging.getLogger("backend.sign_tasks").exception(
                    "后台签到任务异常退出: account=%s task=%s",
                    account_name,
                    task_name,
                )
                self._active_tasks[task_key] = False
                raise
            finally:
                self._starting_tasks.discard(task_key)

        self._starting_tasks.add(task_key)
        background_task = asyncio.create_task(
            _run_in_background(),
            name=f"sign-task:{account_name}:{task_name}",
        )

        def _consume_background_result(task: asyncio.Task) -> None:
            try:
                task.result()
            except asyncio.CancelledError:
                logging.getLogger("backend.sign_tasks").warning(
                    "后台签到任务被取消: account=%s task=%s",
                    account_name,
                    task_name,
                )
            except Exception:
                # The coroutine already logged the traceback; consuming the result
                # prevents asyncio from reporting an unhandled task exception.
                pass

        background_task.add_done_callback(_consume_background_result)
        return {
            "success": True,
            "output": "",
            "error": "",
            "started": True,
            "code": "",
        }

    def _task_key(self, account_name: str, task_name: str) -> tuple[str, str]:
        return account_name, task_name

    def _find_task_keys(self, task_name: str) -> List[tuple[str, str]]:
        return [key for key in self._active_logs.keys() if key[1] == task_name]

    def get_active_logs(
        self, task_name: str, account_name: Optional[str] = None
    ) -> List[str]:
        """获取正在运行任务的日志"""
        if account_name:
            return self._active_logs.get(self._task_key(account_name, task_name), [])
        # 兼容旧接口：返回第一个同名任务的日志
        for key in self._find_task_keys(task_name):
            return self._active_logs.get(key, [])
        return []

    def get_active_logs_snapshot(
        self, task_name: str, account_name: Optional[str] = None
    ) -> tuple[int, List[str]]:
        """获取实时日志快照，返回绝对起始偏移与当前日志列表副本"""
        if account_name:
            key = self._task_key(account_name, task_name)
            return self._active_log_offsets.get(key, 0), list(self._active_logs.get(key, []))
        for key in self._find_task_keys(task_name):
            return self._active_log_offsets.get(key, 0), list(self._active_logs.get(key, []))
        return 0, []

    def is_task_running(self, task_name: str, account_name: Optional[str] = None) -> bool:
        """检查任务是否正在运行"""
        if account_name:
            task_key = self._task_key(account_name, task_name)
            return (
                task_key in self._starting_tasks
                or self._active_tasks.get(task_key, False)
            )
        return (
            any(key[1] == task_name for key in self._starting_tasks)
            or any(key[1] == task_name for key, running in self._active_tasks.items() if running)
        )

    async def run_task_with_logs(
        self, account_name: str, task_name: str
    ) -> Dict[str, Any]:
        return await self.executor.run_task_with_logs(account_name, task_name)


# 创建全局实例
_sign_task_service: Optional[SignTaskService] = None


def get_sign_task_service() -> SignTaskService:
    global _sign_task_service
    if _sign_task_service is None:
        _sign_task_service = SignTaskService()
    return _sign_task_service
