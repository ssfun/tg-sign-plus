from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional


class SignTaskManagementService:
    def __init__(self, config_repo, *, get_now, append_scheduler_log):
        self._config_repo = config_repo
        self._get_now = get_now
        self._append_scheduler_log = append_scheduler_log
        self._tasks_cache_ref = None

    def bind_tasks_cache(self, tasks_cache_ref):
        self._tasks_cache_ref = tasks_cache_ref

    def _invalidate_tasks_cache(self) -> None:
        if self._tasks_cache_ref is not None:
            self._tasks_cache_ref["value"] = None

    def list_tasks(self, get_last_run_info, account_name: Optional[str] = None, force_refresh: bool = False) -> List[Dict[str, Any]]:
        cache = self._tasks_cache_ref["value"] if self._tasks_cache_ref is not None else None
        if cache is not None and not force_refresh:
            if account_name:
                return [t for t in cache if t.get("account_name") == account_name]
            return cache

        try:
            tasks = self._config_repo.list_configs(account_name=None)
            for task in tasks:
                if not task.get("last_run"):
                    task["last_run"] = get_last_run_info(
                        task["name"], task.get("account_name", "")
                    )
            if self._tasks_cache_ref is not None:
                self._tasks_cache_ref["value"] = tasks
            if account_name:
                return [t for t in tasks if t.get("account_name") == account_name]
            return tasks
        except Exception:
            return []

    def get_task(self, task_name: str, account_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self._config_repo.get_config(task_name, account_name)

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
            "retry_count": max(int(retry_count or 0), 0),
            "chats": chats,
            "execution_mode": execution_mode,
            "range_start": range_start,
            "range_end": range_end,
        }

        self._config_repo.save_config(task_name, account_name, config)
        self._config_repo.update_next_scheduled_at(task_name, account_name, None)
        self._invalidate_tasks_cache()

        try:
            from backend.scheduler import add_or_update_sign_task_job

            add_or_update_sign_task_job(
                account_name,
                task_name,
                range_start if execution_mode == "range" else sign_at,
                enabled=True,
            )
        except Exception:
            pass

        return {
            "name": task_name,
            "account_name": account_name,
            "sign_at": sign_at,
            "random_seconds": random_seconds,
            "sign_interval": sign_interval,
            "retry_count": config["retry_count"],
            "chats": chats,
            "enabled": True,
            "execution_mode": execution_mode,
            "range_start": range_start,
            "range_end": range_end,
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
        config = {
            "_version": 3,
            "account_name": acc_name,
            "sign_at": sign_at if sign_at is not None else existing["sign_at"],
            "random_seconds": random_seconds if random_seconds is not None else existing["random_seconds"],
            "sign_interval": sign_interval if sign_interval is not None else existing["sign_interval"],
            "retry_count": max(int(retry_count), 0) if retry_count is not None else existing.get("retry_count", 0),
            "chats": chats if chats is not None else existing["chats"],
            "execution_mode": execution_mode if execution_mode is not None else existing.get("execution_mode", "fixed"),
            "range_start": range_start if range_start is not None else existing.get("range_start", ""),
            "range_end": range_end if range_end is not None else existing.get("range_end", ""),
        }

        self._config_repo.save_config(task_name, acc_name, config)
        self._config_repo.update_next_scheduled_at(task_name, acc_name, None)
        self._invalidate_tasks_cache()

        try:
            from backend.scheduler import add_or_update_sign_task_job

            add_or_update_sign_task_job(
                config["account_name"],
                task_name,
                config.get("range_start") if config.get("execution_mode") == "range" else config["sign_at"],
                enabled=True,
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
            "chats": config["chats"],
            "enabled": True,
            "execution_mode": config.get("execution_mode", "fixed"),
            "range_start": config.get("range_start", ""),
            "range_end": config.get("range_end", ""),
        }

    async def update_task_and_sync(self, **kwargs) -> Dict[str, Any]:
        task = self.update_task(**kwargs)
        from backend.scheduler import sync_jobs

        await sync_jobs()
        return task

    def delete_task(self, task_name: str, account_name: Optional[str] = None) -> bool:
        if not account_name:
            raise ValueError("删除任务必须指定账号名称")

        deleted = self._config_repo.delete_config(task_name, account_name)
        if not deleted:
            return False

        self._invalidate_tasks_cache()

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
