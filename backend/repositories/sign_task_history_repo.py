"""
SignTask 运行历史存储层抽象。

当前版本仅保留数据库签到历史存储实现。
"""

from __future__ import annotations

import abc
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional

from backend.services.sign_task_run_summary import compact_run_entry


class SignTaskHistoryRepo(abc.ABC):
    """SignTask 运行历史存储抽象基类"""

    @abc.abstractmethod
    def load_entries(
        self, task_name: str, account_name: str = "", *, limit: int | None = None,
        cutoff: datetime | None = None,
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
    def get_account_history(self, account_name: str, *, limit: int | None = None, cutoff: datetime | None = None) -> List[Dict[str, Any]]:
        ...

    @abc.abstractmethod
    def clear_account_history(self, account_name: str) -> Dict[str, int]:
        ...

    @abc.abstractmethod
    def prune_older_than(self, cutoff: datetime) -> Dict[str, int]:
        ...

class DatabaseSignTaskHistoryRepo(SignTaskHistoryRepo):
    """基于数据库 sign_task_runs 表的历史存储"""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def _get_db(self):
        return self._session_factory()

    def load_entries(
        self, task_name: str, account_name: str = "", *, limit: int | None = None,
        cutoff: datetime | None = None,
    ) -> List[Dict[str, Any]]:
        from backend.models.sign_task_run import SignTaskRun

        db = self._get_db()
        try:
            q = db.query(SignTaskRun).filter_by(task_name=task_name)
            if account_name:
                q = q.filter_by(account_name=account_name)
            if cutoff is not None:
                q = q.filter(SignTaskRun.created_at >= self._utc_cutoff(cutoff))
            q = q.order_by(SignTaskRun.created_at.desc(), SignTaskRun.id.desc())
            if limit is not None:
                q = q.limit(limit)
            rows = q.all()
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
            if isinstance(flow_items, list):
                stored_flow_items = [item for item in flow_items if isinstance(item, dict)]
            else:
                stored_flow_items = []
            row = SignTaskRun(
                account_name=account_name,
                task_name=task_name,
                success=entry.get("success", False),
                message=entry.get("message", ""),
                flow_logs=json.dumps(flow_logs, ensure_ascii=False) if flow_logs else None,
                flow_items=json.dumps(stored_flow_items, ensure_ascii=False) if stored_flow_items else None,
                summary_json=json.dumps(compact_run_entry(entry), ensure_ascii=False),
                flow_truncated=entry.get("flow_truncated", False),
                flow_line_count=entry.get("flow_line_count", 0),
            )
            db.add(row)
            db.flush()

            # Prune IDs in SQL without materializing obsolete diagnostic bodies.
            old_ids = (
                db.query(SignTaskRun.id)
                .filter_by(account_name=account_name, task_name=task_name)
                .order_by(SignTaskRun.created_at.desc(), SignTaskRun.id.desc())
                .offset(max_entries)
                .subquery()
            )
            from sqlalchemy import select
            db.query(SignTaskRun).filter(SignTaskRun.id.in_(select(old_ids.c.id))).delete(synchronize_session=False)

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
            row = q.order_by(SignTaskRun.created_at.desc(), SignTaskRun.id.desc()).first()
            return self._row_to_dict(row) if row else None
        finally:
            db.close()

    def get_account_history(self, account_name: str, *, limit: int | None = None, cutoff: datetime | None = None) -> List[Dict[str, Any]]:
        from backend.models.sign_task_run import SignTaskRun

        db = self._get_db()
        try:
            query = (
                db.query(SignTaskRun)
                .filter_by(account_name=account_name)
                .order_by(SignTaskRun.created_at.desc(), SignTaskRun.id.desc())
            )
            if cutoff is not None:
                query = query.filter(SignTaskRun.created_at >= self._utc_cutoff(cutoff))
            if limit is not None:
                query = query.limit(limit)
            rows = query.all()
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

    def prune_older_than(self, cutoff: datetime) -> Dict[str, int]:
        from backend.models.sign_task_run import SignTaskRun

        cutoff = self._utc_cutoff(cutoff)

        db = self._get_db()
        try:
            count = db.query(SignTaskRun).filter(SignTaskRun.created_at < cutoff).delete()
            db.commit()
            return {"removed_entries": count}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _utc_cutoff(cutoff: datetime) -> datetime:
        return cutoff.astimezone(timezone.utc).replace(tzinfo=None) if cutoff.tzinfo else cutoff

    @staticmethod
    def _summary_columns():
        from sqlalchemy import case
        from backend.models.sign_task_run import SignTaskRun as Run

        # Legacy rows have no summary column. Fetch their bodies in this same
        # query, never one lazy-load query per task. New rows read only metadata.
        return (
            Run.account_name, Run.task_name, Run.created_at, Run.success, Run.message,
            Run.summary_json, Run.flow_truncated, Run.flow_line_count,
            case((Run.summary_json.is_(None), Run.flow_items), else_=None).label("flow_items"),
            case((Run.summary_json.is_(None), Run.flow_logs), else_=None).label("flow_logs"),
        )

    @classmethod
    def _row_to_summary(cls, row):
        if row.summary_json:
            summary = json.loads(row.summary_json)
            summary.update(time=cls._format_time(row.created_at), success=row.success, message=row.message or "")
            return compact_run_entry(summary)
        return compact_run_entry(cls._row_to_dict(row))

    def get_latest_summary(self, task_name: str, account_name: str = "") -> Optional[Dict[str, Any]]:
        from backend.models.sign_task_run import SignTaskRun as Run

        with self._get_db() as db:
            q = db.query(*self._summary_columns()).filter(Run.task_name == task_name)
            if account_name:
                q = q.filter(Run.account_name == account_name)
            row = q.order_by(Run.created_at.desc(), Run.id.desc()).first()
            return self._row_to_summary(row) if row else None

    def get_latest_summaries(self, account_name: str | None = None) -> Dict[tuple[str, str], Dict[str, Any]]:
        from sqlalchemy import func
        from backend.models.sign_task_run import SignTaskRun as Run

        with self._get_db() as db:
            ranked = db.query(Run.id, func.row_number().over(
                partition_by=(Run.account_name, Run.task_name),
                order_by=(Run.created_at.desc(), Run.id.desc()),
            ).label("position"))
            if account_name:
                ranked = ranked.filter(Run.account_name == account_name)
            ranked = ranked.subquery()
            rows = db.query(*self._summary_columns()).join(ranked, Run.id == ranked.c.id).filter(ranked.c.position == 1).all()
            return {(r.account_name, r.task_name): self._row_to_summary(r) for r in rows}

    def get_history_marker(self, task_name: str, account_name: str, cutoff: datetime | None = None) -> str:
        from sqlalchemy import func
        from backend.models.sign_task_run import SignTaskRun as Run

        with self._get_db() as db:
            q = db.query(func.max(Run.id), func.count(Run.id)).filter_by(task_name=task_name, account_name=account_name)
            if cutoff is not None:
                q = q.filter(Run.created_at >= self._utc_cutoff(cutoff))
            latest, count = q.one()
            return f"{latest or 0}:{count}"

    @staticmethod
    def _row_to_dict(row) -> Dict[str, Any]:
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

        run_summary, public_flow_items = DatabaseSignTaskHistoryRepo._split_run_summary(flow_items)
        if getattr(row, "summary_json", None):
            run_summary = json.loads(row.summary_json).get("run_summary") or run_summary

        return {
            "time": DatabaseSignTaskHistoryRepo._format_time(row.created_at),
            "success": row.success,
            "message": row.message or "",
            "account_name": row.account_name,
            "flow_logs": flow_logs,
            "flow_items": public_flow_items,
            "run_summary": run_summary,
            "flow_truncated": row.flow_truncated,
            "flow_line_count": row.flow_line_count,
        }

    @staticmethod
    def _format_time(created_at) -> str:
        from backend.core.config import get_settings

        if created_at:
            try:
                tz = ZoneInfo(get_settings().timezone)
            except Exception:
                tz = timezone.utc
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            return created_at.astimezone(tz).isoformat()
        return ""

    @staticmethod
    def _extract_run_summary(flow_items: List[Dict[str, Any]]) -> Dict[str, Any]:
        return DatabaseSignTaskHistoryRepo._split_run_summary(flow_items)[0]

    @staticmethod
    def _split_run_summary(
        flow_items: List[Dict[str, Any]]
    ) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        public_items: List[Dict[str, Any]] = []
        run_summary: Dict[str, Any] = {}
        for item in flow_items:
            if isinstance(item, dict) and item.get("event") == "run_summary":
                meta = item.get("meta")
                if isinstance(meta, dict):
                    run_summary = meta
                continue
            public_items.append(item)
        return run_summary, public_items


_repo: Optional[SignTaskHistoryRepo] = None


def get_sign_task_history_repo() -> SignTaskHistoryRepo:
    """获取 SignTask 历史存储实例（单例）"""
    global _repo
    if _repo is not None:
        return _repo

    from backend.core.database import get_session_local

    _repo = DatabaseSignTaskHistoryRepo(get_session_local())
    return _repo
