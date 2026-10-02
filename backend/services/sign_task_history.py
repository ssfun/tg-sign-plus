from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from backend.core.config import get_settings
from backend.services.config import get_config_service
from backend.services.sign_task_diagnostics import analyze_sign_task_run
from backend.services.sign_task_event_presets import normalize_event_task_config
from backend.services.sign_task_run_summary import (
    build_flow_event_counts,
    build_run_summary,
    compact_run_entry,
    sanitize_public_run_summary,
)

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
                    "text_visible": bool(item.get("text_visible", True)),
                }
            )
        return trimmed

    @staticmethod
    def _normalize_run_summary(value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        normalized: Dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(item, dict):
                nested = {
                    str(nested_key): nested_value
                    if isinstance(nested_value, (str, int, float, bool)) or nested_value is None
                    else str(nested_value)
                    for nested_key, nested_value in item.items()
                }
                normalized[str(key)] = nested
            elif isinstance(item, (str, int, float, bool)) or item is None:
                normalized[str(key)] = item
            else:
                normalized[str(key)] = str(item)
        return sanitize_public_run_summary(normalized)

    def _get_log_retention_days(self) -> int:
        try:
            value = get_config_service().get_global_settings().get("log_retention_days", 7)
            return int(value or 0)
        except (TypeError, ValueError):
            return 7

    def retention_cutoff(self) -> datetime | None:
        days = self._get_log_retention_days()
        return self._now() - timedelta(days=days) if days > 0 else None

    def prune_expired_history_logs(self) -> Dict[str, int]:
        cutoff = self.retention_cutoff()
        return self._history_repo.prune_older_than(cutoff) if cutoff else {"removed_entries": 0}

    def load_history_entries(
        self, task_name: str, account_name: str = "", *, limit: int | None = None
    ) -> List[Dict[str, Any]]:
        return self._history_repo.load_entries(task_name, account_name, limit=limit, cutoff=self.retention_cutoff())

    def get_task_history_logs(
        self, task_name: str, account_name: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        if limit < 1:
            limit = 1
        if limit > 200:
            limit = 200

        history = self.load_history_entries(task_name, account_name=account_name, limit=limit)
        result: List[Dict[str, Any]] = []
        task_config = self._find_task_config(task_name, account_name)
        for item in history:
            result.append(
                self._normalize_run_entry(
                    item,
                    task_config=task_config,
                    include_diagnostics=True,
                )
            )
        return result

    def _normalize_run_entry(
        self,
        item: Dict[str, Any],
        *,
        task_config: Optional[Dict[str, Any]] = None,
        include_diagnostics: bool = False,
    ) -> Dict[str, Any]:
        flow_logs = item.get("flow_logs")
        if not isinstance(flow_logs, list):
            flow_logs = []
        flow_items = self._normalize_flow_items(item.get("flow_items"))
        success = bool(item.get("success", False))
        message = str(item.get("message", "") or "")
        run_summary = self._normalize_run_summary(item.get("run_summary"))
        if not run_summary:
            run_summary = build_run_summary(
                flow_items,
                success=success,
                error="" if success else message,
            )

        result = {
            "time": item.get("time", ""),
            "success": success,
            "message": message,
            "flow_logs": [str(line) for line in flow_logs],
            "flow_items": flow_items,
            "flow_event_counts": build_flow_event_counts(flow_items),
            "flow_truncated": bool(item.get("flow_truncated", False)),
            "flow_line_count": int(item.get("flow_line_count", len(flow_logs))),
            "run_summary": run_summary,
        }
        if include_diagnostics:
            result["diagnostics"] = analyze_sign_task_run(
                flow_items=flow_items,
                task_config=task_config,
                success=success,
            )
        return result

    def _find_task_config(self, task_name: str, account_name: str) -> Optional[Dict[str, Any]]:
        def normalize(config: Dict[str, Any]) -> Dict[str, Any]:
            try:
                return normalize_event_task_config(config)
            except Exception:
                return config

        get_config = getattr(self._config_repo, "get_config", None)
        if callable(get_config):
            task = get_config(task_name, account_name)
            if isinstance(task, dict):
                return normalize({
                    "engine": task.get("engine", "event"),
                    "chats": task.get("chats") or [],
                })
        return None

    def get_account_history_logs(self, account_name: str, limit: int | None = None) -> List[Dict[str, Any]]:
        history = self._history_repo.get_account_history(account_name, limit=limit, cutoff=self.retention_cutoff())
        result: List[Dict[str, Any]] = []
        for item in history:
            if not isinstance(item, dict):
                continue
            normalized = self._normalize_run_entry(item)
            normalized["task_name"] = item.get("task_name", "")
            normalized["account_name"] = item.get("account_name", account_name)
            result.append(normalized)
        return result

    def clear_account_history_logs(self, account_name: str, tasks: List[Dict[str, Any]]) -> Dict[str, int]:
        for task in tasks:
            task_name = task.get("name") or ""
            if not task_name:
                continue
            self._config_repo.clear_last_run(task_name, account_name)

        return self._history_repo.clear_account_history(account_name)

    def get_last_run_info(self, task_name: str, account_name: str = "") -> Optional[Dict[str, Any]]:
        entry = self._history_repo.get_latest_summary(task_name, account_name)
        if not isinstance(entry, dict):
            return None
        return compact_run_entry(entry)

    def save_run_info(
        self,
        task_name: str,
        success: bool,
        message: str = "",
        account_name: str = "",
        flow_logs: Optional[List[str]] = None,
        flow_items: Optional[List[Dict[str, Any]]] = None,
        run_summary: Optional[Dict[str, Any]] = None,
    ) -> None:
        normalized_logs, flow_truncated, flow_line_count = self._normalize_flow_logs(flow_logs)
        normalized_items = self._normalize_flow_items(flow_items)
        normalized_summary = self._normalize_run_summary(run_summary)
        if not normalized_summary:
            normalized_summary = build_run_summary(
                normalized_items,
                success=success,
                error="" if success else message,
            )

        new_entry = {
            "time": self._now_isoformat(),
            "success": success,
            "message": message,
            "account_name": account_name,
            "flow_logs": normalized_logs,
            "flow_items": normalized_items,
            "flow_event_counts": build_flow_event_counts(normalized_items),
            "flow_truncated": flow_truncated,
            "flow_line_count": flow_line_count,
            "run_summary": normalized_summary,
        }

        self._history_repo.save_entry(
            task_name,
            account_name,
            new_entry,
            max_entries=self._history_max_entries,
        )
        self._config_repo.update_last_run(task_name, account_name, compact_run_entry(new_entry))
