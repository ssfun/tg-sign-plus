from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from backend.core.config import get_settings

settings = get_settings()


class SignTaskHistoryService:
    def __init__(
        self,
        history_repo,
        config_repo,
        *,
        history_max_entries: int,
        history_max_flow_lines: int,
        history_max_line_chars: int,
    ):
        self._history_repo = history_repo
        self._config_repo = config_repo
        self._history_max_entries = history_max_entries
        self._history_max_flow_lines = history_max_flow_lines
        self._history_max_line_chars = history_max_line_chars
        self._tasks_cache_ref: Optional[list] = None

    def bind_tasks_cache(self, tasks_cache_ref: Optional[list]) -> None:
        self._tasks_cache_ref = tasks_cache_ref

    @staticmethod
    def _get_timezone() -> ZoneInfo:
        try:
            return ZoneInfo(settings.timezone)
        except Exception:
            return ZoneInfo("UTC")

    @classmethod
    def _now(cls) -> datetime:
        return datetime.now(cls._get_timezone())

    @classmethod
    def _now_isoformat(cls) -> str:
        return cls._now().isoformat()

    def _normalize_flow_logs(
        self, flow_logs: Optional[List[str]]
    ) -> tuple[List[str], bool, int]:
        if not isinstance(flow_logs, list):
            return [], False, 0

        total = len(flow_logs)
        trimmed: List[str] = []
        for line in flow_logs[: self._history_max_flow_lines]:
            text = str(line).replace("\r", "").rstrip("\n")
            if len(text) > self._history_max_line_chars:
                text = text[: self._history_max_line_chars] + "..."
            trimmed.append(text)
        return trimmed, total > len(trimmed), total

    def _normalize_flow_items(
        self, flow_items: Optional[List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        if not isinstance(flow_items, list):
            return []

        trimmed: List[Dict[str, Any]] = []
        for item in flow_items[: self._history_max_flow_lines]:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).replace("\r", "").rstrip("\n")
            if len(text) > self._history_max_line_chars:
                text = text[: self._history_max_line_chars] + "..."
            meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
            normalized_meta = {
                str(key): value if isinstance(value, (str, int, float, bool)) or value is None else str(value)
                for key, value in meta.items()
            }
            trimmed.append(
                {
                    "ts": str(item.get("ts", "") or ""),
                    "level": str(item.get("level", "info") or "info"),
                    "stage": str(item.get("stage", "task") or "task"),
                    "event": str(item.get("event", "info") or "info"),
                    "text": text,
                    "meta": normalized_meta,
                }
            )
        return trimmed

    def load_history_entries(
        self, task_name: str, account_name: str = ""
    ) -> List[Dict[str, Any]]:
        return self._history_repo.load_entries(task_name, account_name)

    def get_task_history_logs(
        self, task_name: str, account_name: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        if limit < 1:
            limit = 1
        if limit > 200:
            limit = 200

        history = self.load_history_entries(task_name, account_name=account_name)
        result: List[Dict[str, Any]] = []
        for item in history[:limit]:
            flow_logs = item.get("flow_logs")
            if not isinstance(flow_logs, list):
                flow_logs = []

            result.append(
                {
                    "time": item.get("time", ""),
                    "success": bool(item.get("success", False)),
                    "message": item.get("message", "") or "",
                    "flow_logs": [str(line) for line in flow_logs],
                    "flow_items": self._normalize_flow_items(item.get("flow_items")),
                    "flow_truncated": bool(item.get("flow_truncated", False)),
                    "flow_line_count": int(item.get("flow_line_count", len(flow_logs))),
                }
            )
        return result

    def get_account_history_logs(self, account_name: str) -> List[Dict[str, Any]]:
        return self._history_repo.get_account_history(account_name)

    def clear_account_history_logs(self, account_name: str, tasks: List[Dict[str, Any]]) -> Dict[str, int]:
        for task in tasks:
            task_name = task.get("name") or ""
            if not task_name:
                continue
            self._config_repo.clear_last_run(task_name, account_name)
            if self._tasks_cache_ref is not None:
                for cache_task in self._tasks_cache_ref:
                    if cache_task["name"] == task_name and cache_task.get("account_name") == account_name:
                        cache_task.pop("last_run", None)
                        break

        return self._history_repo.clear_account_history(account_name)

    def get_last_run_info(self, task_name: str, account_name: str = "") -> Optional[Dict[str, Any]]:
        return self._history_repo.get_latest(task_name, account_name)

    def save_run_info(
        self,
        task_name: str,
        success: bool,
        message: str = "",
        account_name: str = "",
        flow_logs: Optional[List[str]] = None,
        flow_items: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        normalized_logs, flow_truncated, flow_line_count = self._normalize_flow_logs(flow_logs)
        normalized_items = self._normalize_flow_items(flow_items)

        new_entry = {
            "time": self._now_isoformat(),
            "success": success,
            "message": message,
            "account_name": account_name,
            "flow_logs": normalized_logs,
            "flow_items": normalized_items,
            "flow_truncated": flow_truncated,
            "flow_line_count": flow_line_count,
        }

        self._history_repo.save_entry(
            task_name,
            account_name,
            new_entry,
            max_entries=self._history_max_entries,
        )
        self._config_repo.update_last_run(task_name, account_name, new_entry)

        if self._tasks_cache_ref is not None:
            for cache_task in self._tasks_cache_ref:
                if cache_task["name"] == task_name and cache_task.get("account_name") == account_name:
                    cache_task["last_run"] = new_entry
                    break
