from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from backend.services.sign_task_event_presets import (
    normalize_event_task_config,
    validate_writable_event_task_config,
)
from backend.services.sign_task_run_summary import (
    compact_run_entry,
)


class SignTaskManagementService:
    def __init__(self, config_repo, *, get_now, append_scheduler_log):
        self._config_repo = config_repo
        self._get_now = get_now
        self._append_scheduler_log = append_scheduler_log

    def _normalize_loaded_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(task, dict):
            return task
        normalized = normalize_event_task_config(task)
        if normalized == task:
            return task
        task_name = normalized.get("name") or task.get("name")
        account_name = normalized.get("account_name") or task.get("account_name") or ""
        if task_name and account_name:
            try:
                self._config_repo.save_config(task_name, account_name, normalized)
            except Exception:
                logging.getLogger("backend.sign_tasks").warning(
                    "Failed to persist normalized sign task config: %s/%s",
                    account_name,
                    task_name,
                    exc_info=True,
                )
        return normalized

    @staticmethod
    def _attach_last_run(
        task: Dict[str, Any],
        get_last_run_info,
    ) -> Dict[str, Any]:
        if not isinstance(task, dict):
            return task
        if not callable(get_last_run_info):
            SignTaskManagementService._normalize_cached_last_run(task)
            return task
        task_name = task.get("name")
        if not task_name:
            SignTaskManagementService._normalize_cached_last_run(task)
            return task
        try:
            latest = get_last_run_info(task_name, task.get("account_name", ""))
        except Exception:
            logging.getLogger("backend.sign_tasks").warning(
                "Failed to load latest sign task run: %s/%s",
                task.get("account_name", ""),
                task_name,
                exc_info=True,
            )
            SignTaskManagementService._normalize_cached_last_run(task)
            return task
        if latest:
            task["last_run"] = latest
        else:
            SignTaskManagementService._normalize_cached_last_run(task)
        return task

    @staticmethod
    def _normalize_cached_last_run(task: Dict[str, Any]) -> None:
        last_run = task.get("last_run")
        if isinstance(last_run, dict):
            task["last_run"] = compact_run_entry(last_run)
        else:
            task.pop("last_run", None)

    def list_tasks(self, get_last_run_infos, account_name: Optional[str] = None) -> List[Dict[str, Any]]:
        tasks = [self._normalize_loaded_task(task) for task in self._config_repo.list_configs(account_name)]
        if not tasks:
            return []
        summaries = get_last_run_infos(account_name)
        for task in tasks:
            latest = summaries.get((task.get("account_name", ""), task["name"]))
            if latest:
                task["last_run"] = latest
            else:
                self._normalize_cached_last_run(task)
        return tasks

    def get_task(
        self,
        task_name: str,
        account_name: Optional[str] = None,
        get_last_run_info=None,
    ) -> Optional[Dict[str, Any]]:
        task = self._config_repo.get_config(task_name, account_name)
        if not task:
            return None
        return self._attach_last_run(
            self._normalize_loaded_task(task),
            get_last_run_info,
        )

    def create_task(
        self,
        *,
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
        import random
        from backend.services.config import get_config_service

        if not account_name:
            raise ValueError("必须指定账号名称")

        if sign_interval is None:
            config_service = get_config_service()
            global_settings = config_service.get_global_settings()
            sign_interval = global_settings.get("sign_interval")

        if sign_interval is None:
            sign_interval = random.randint(1, 120)

        config = {
            "_version": 3,
            "account_name": account_name,
            "sign_at": sign_at,
            "random_seconds": random_seconds,
            "sign_interval": sign_interval,
            "retry_count": retry_count,
            "engine": "event",
            "chats": chats,
            "execution_mode": execution_mode,
            "range_start": range_start,
            "range_end": range_end,
            "enabled": True,
        }
        validate_writable_event_task_config(config)
        config = normalize_event_task_config(config)
        normalized_chats = config["chats"]

        self._config_repo.save_config(task_name, account_name, config)
        self._config_repo.update_next_scheduled_at(task_name, account_name, None)

        try:
            from backend.scheduler import add_or_update_sign_task_job

            add_or_update_sign_task_job(
                account_name,
                task_name,
                config.get("range_start") if config.get("execution_mode") == "range" else config["sign_at"],
                enabled=True,
            )
        except Exception:
            pass

        return {
            "name": task_name,
            "account_name": account_name,
            "sign_at": config["sign_at"],
            "random_seconds": config["random_seconds"],
            "sign_interval": config["sign_interval"],
            "retry_count": config["retry_count"],
            "engine": config["engine"],
            "chats": normalized_chats,
            "enabled": True,
            "execution_mode": config.get("execution_mode", "fixed"),
            "range_start": config.get("range_start", ""),
            "range_end": config.get("range_end", ""),
            "next_scheduled_at": None,
        }

    async def create_task_and_sync(self, **kwargs) -> Dict[str, Any]:
        task = self.create_task(**kwargs)
        from backend.scheduler import sync_jobs

        await sync_jobs()
        return task

    def update_task(
        self,
        *,
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
        existing = self.get_task(task_name, account_name)
        if not existing:
            raise ValueError(f"任务 {task_name} 不存在")

        acc_name = account_name if account_name is not None else existing.get("account_name", "")
        next_chats = chats if chats is not None else existing["chats"]
        config = {
            "_version": 3,
            "account_name": acc_name,
            "sign_at": sign_at if sign_at is not None else existing["sign_at"],
            "random_seconds": random_seconds if random_seconds is not None else existing["random_seconds"],
            "sign_interval": sign_interval if sign_interval is not None else existing["sign_interval"],
            "retry_count": retry_count if retry_count is not None else existing.get("retry_count", 0),
            "engine": "event",
            "chats": next_chats,
            "execution_mode": execution_mode if execution_mode is not None else existing.get("execution_mode", "fixed"),
            "range_start": range_start if range_start is not None else existing.get("range_start", ""),
            "range_end": range_end if range_end is not None else existing.get("range_end", ""),
            "enabled": bool(existing.get("enabled", True)),
        }
        validate_writable_event_task_config(config)
        config = normalize_event_task_config(config)
        normalized_chats = config["chats"]

        self._config_repo.save_config(task_name, acc_name, config)
        self._config_repo.update_next_scheduled_at(task_name, acc_name, None)

        try:
            from backend.scheduler import add_or_update_sign_task_job

            add_or_update_sign_task_job(
                config["account_name"],
                task_name,
                config.get("range_start") if config.get("execution_mode") == "range" else config["sign_at"],
                enabled=config["enabled"],
            )
        except Exception as e:
            msg = f"DEBUG: 更新调度任务失败: {e}"
            print(msg)
            self._append_scheduler_log("scheduler_error.log", f"{self._get_now()}: {msg}")
        else:
            self._append_scheduler_log(
                "scheduler_update.log",
                f"{self._get_now()}: Updated task {task_name} with cron {config.get('range_start') if config.get('execution_mode') == 'range' else config['sign_at']}",
            )

        return {
            "name": task_name,
            "account_name": config["account_name"],
            "sign_at": config["sign_at"],
            "random_seconds": config["random_seconds"],
            "sign_interval": config["sign_interval"],
            "retry_count": config["retry_count"],
            "engine": "event",
            "chats": config["chats"],
            "enabled": config["enabled"],
            "execution_mode": config.get("execution_mode", "fixed"),
            "range_start": config.get("range_start", ""),
            "range_end": config.get("range_end", ""),
            "next_scheduled_at": None,
        }

    async def update_task_and_sync(self, **kwargs) -> Dict[str, Any]:
        task = self.update_task(**kwargs)
        from backend.scheduler import sync_jobs

        await sync_jobs()
        return task

    def set_task_enabled(self, task_name: str, account_name: str, enabled: bool) -> Dict[str, Any]:
        if not account_name:
            raise ValueError("切换自动调度必须指定账号名称")

        existing = self.get_task(task_name, account_name)
        if not existing:
            raise ValueError(f"任务 {task_name} 不存在")

        self._config_repo.set_enabled(task_name, account_name, enabled)
        if not enabled:
            self._config_repo.update_next_scheduled_at(task_name, account_name, None)

        task = self.get_task(task_name, account_name)
        if task is None:
            raise ValueError(f"任务 {task_name} 不存在")
        return task

    async def set_task_enabled_and_sync(self, task_name: str, account_name: str, enabled: bool) -> Dict[str, Any]:
        task = self.set_task_enabled(task_name, account_name, enabled)
        from backend.scheduler import sync_jobs

        await sync_jobs(schedule_range_catchup=enabled)
        refreshed = self.get_task(task_name, account_name)
        return refreshed or task

    def delete_task(self, task_name: str, account_name: Optional[str] = None) -> bool:
        if not account_name:
            raise ValueError("删除任务必须指定账号名称")

        deleted = self._config_repo.delete_config(task_name, account_name)
        if not deleted:
            return False


        try:
            from backend.scheduler import remove_sign_task_job

            remove_sign_task_job(account_name, task_name)
        except Exception:
            pass

        return True

    async def delete_task_and_sync(self, task_name: str, account_name: Optional[str] = None) -> bool:
        deleted = self.delete_task(task_name, account_name=account_name)
        if not deleted:
            return False
        from backend.scheduler import sync_jobs

        await sync_jobs()
        return True
