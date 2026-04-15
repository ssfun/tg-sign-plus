from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from backend.core.config import get_settings

settings = get_settings()


class TaskFlowLogger:
    def __init__(
        self,
        text_logs: List[str],
        flow_items: List[Dict[str, Any]],
        offset_ref: Dict[str, int],
        *,
        max_lines: int = 1000,
    ):
        self._text_logs = text_logs
        self._flow_items = flow_items
        self._offset_ref = offset_ref
        self._max_lines = max_lines

    @staticmethod
    def _now_iso() -> str:
        try:
            return datetime.now(ZoneInfo(settings.timezone)).isoformat()
        except Exception:
            return datetime.now().isoformat()

    @staticmethod
    def _short_ts(iso_ts: str) -> str:
        try:
            return datetime.fromisoformat(iso_ts).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return iso_ts

    @staticmethod
    def _normalize_meta(meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(meta, dict):
            return {}
        normalized: Dict[str, Any] = {}
        for key, value in meta.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                normalized[str(key)] = value
            else:
                normalized[str(key)] = str(value)
        return normalized

    def append(
        self,
        text: str,
        *,
        level: str = "info",
        stage: str = "task",
        event: str = "info",
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ts = self._now_iso()
        item = {
            "ts": ts,
            "level": (level or "info").lower(),
            "stage": stage or "task",
            "event": event or "info",
            "text": str(text),
            "meta": self._normalize_meta(meta),
        }
        self._flow_items.append(item)
        self._text_logs.append(f"{self._short_ts(ts)} - {text}")
        while len(self._text_logs) > self._max_lines:
            self._text_logs.pop(0)
            if self._flow_items:
                self._flow_items.pop(0)
            self._offset_ref["value"] += 1
        return item
