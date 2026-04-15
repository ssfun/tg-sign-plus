"""
SignTask 运行历史存储层抽象。

当前版本仅保留数据库签到历史存储实现。
"""

from __future__ import annotations

import abc
import json
from datetime import UTC
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional


class SignTaskHistoryRepo(abc.ABC):
    """SignTask 运行历史存储抽象基类"""

    @abc.abstractmethod
    def load_entries(
        self, task_name: str, account_name: str = ""
    ) -> List[Dict[str, Any]]:
        ...

    @abc.abstractmethod
    def save_entry(
        self,
        task_name: str,
        account_name: str,
        entry: Dict[str, Any],
        max_entries: int = 100,
    ) -> None:
        ...

    @abc.abstractmethod
    def get_latest(
        self, task_name: str, account_name: str = ""
    ) -> Optional[Dict[str, Any]]:
        ...

    @abc.abstractmethod
    def get_account_history(self, account_name: str) -> List[Dict[str, Any]]:
        ...

    @abc.abstractmethod
    def clear_account_history(self, account_name: str) -> Dict[str, int]:
        ...


class DatabaseSignTaskHistoryRepo(SignTaskHistoryRepo):
    """基于数据库 sign_task_runs 表的历史存储"""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def _get_db(self):
        return self._session_factory()

    def load_entries(
        self, task_name: str, account_name: str = ""
    ) -> List[Dict[str, Any]]:
        from backend.models.sign_task_run import SignTaskRun

        db = self._get_db()
        try:
            q = db.query(SignTaskRun).filter_by(task_name=task_name)
            if account_name:
                q = q.filter_by(account_name=account_name)
            rows = q.order_by(SignTaskRun.created_at.desc()).all()
            return [self._row_to_dict(r) for r in rows]
        finally:
            db.close()

    def save_entry(
        self,
        task_name: str,
        account_name: str,
        entry: Dict[str, Any],
        max_entries: int = 100,
    ) -> None:
        from backend.models.sign_task_run import SignTaskRun

        db = self._get_db()
        try:
            flow_logs = entry.get("flow_logs", [])
            flow_items = entry.get("flow_items", [])
            row = SignTaskRun(
                account_name=account_name,
                task_name=task_name,
                success=entry.get("success", False),
                message=entry.get("message", ""),
                flow_logs=json.dumps(flow_logs, ensure_ascii=False) if flow_logs else None,
                flow_items=json.dumps(flow_items, ensure_ascii=False) if flow_items else None,
                flow_truncated=entry.get("flow_truncated", False),
                flow_line_count=entry.get("flow_line_count", 0),
            )
            db.add(row)
            db.flush()

            count = (
                db.query(SignTaskRun)
                .filter_by(account_name=account_name, task_name=task_name)
                .count()
            )
            if count > max_entries:
                oldest = (
                    db.query(SignTaskRun)
                    .filter_by(account_name=account_name, task_name=task_name)
                    .order_by(SignTaskRun.created_at.asc())
                    .limit(count - max_entries)
                    .all()
                )
                for old in oldest:
                    db.delete(old)

            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get_latest(
        self, task_name: str, account_name: str = ""
    ) -> Optional[Dict[str, Any]]:
        from backend.models.sign_task_run import SignTaskRun

        db = self._get_db()
        try:
            q = db.query(SignTaskRun).filter_by(task_name=task_name)
            if account_name:
                q = q.filter_by(account_name=account_name)
            row = q.order_by(SignTaskRun.created_at.desc()).first()
            return self._row_to_dict(row) if row else None
        finally:
            db.close()

    def get_account_history(self, account_name: str) -> List[Dict[str, Any]]:
        from backend.models.sign_task_run import SignTaskRun

        db = self._get_db()
        try:
            rows = (
                db.query(SignTaskRun)
                .filter_by(account_name=account_name)
                .order_by(SignTaskRun.created_at.desc())
                .all()
            )
            result = []
            for r in rows:
                d = self._row_to_dict(r)
                d["task_name"] = r.task_name
                result.append(d)
            return result
        finally:
            db.close()

    def clear_account_history(self, account_name: str) -> Dict[str, int]:
        from backend.models.sign_task_run import SignTaskRun

        db = self._get_db()
        try:
            count = db.query(SignTaskRun).filter_by(account_name=account_name).delete()
            db.commit()
            return {"removed_entries": count}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _row_to_dict(row) -> Dict[str, Any]:
        from backend.core.config import get_settings

        flow_logs = []
        if row.flow_logs:
            try:
                flow_logs = json.loads(row.flow_logs)
            except Exception:
                pass

        flow_items = []
        if getattr(row, "flow_items", None):
            try:
                flow_items = json.loads(row.flow_items)
            except Exception:
                pass

        created_at = row.created_at
        if created_at:
            try:
                tz = ZoneInfo(get_settings().timezone)
            except Exception:
                tz = UTC
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            created_at_str = created_at.astimezone(tz).isoformat()
        else:
            created_at_str = ""

        return {
            "time": created_at_str,
            "success": row.success,
            "message": row.message or "",
            "account_name": row.account_name,
            "flow_logs": flow_logs,
            "flow_items": flow_items,
            "flow_truncated": row.flow_truncated,
            "flow_line_count": row.flow_line_count,
        }


_repo: Optional[SignTaskHistoryRepo] = None


def get_sign_task_history_repo() -> SignTaskHistoryRepo:
    """获取 SignTask 历史存储实例（单例）"""
    global _repo
    if _repo is not None:
        return _repo

    from backend.core.database import get_session_local

    _repo = DatabaseSignTaskHistoryRepo(get_session_local())
    return _repo
