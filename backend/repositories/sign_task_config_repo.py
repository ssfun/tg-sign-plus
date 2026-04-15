"""
SignTask 配置存储层抽象。

当前版本仅保留数据库签到任务配置存储实现。
"""

from __future__ import annotations

import abc
import json
from datetime import datetime
from typing import Any, Dict, List, Optional


class SignTaskConfigRepo(abc.ABC):
    """SignTask 配置存储抽象基类"""

    @abc.abstractmethod
    def list_configs(
        self, account_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        ...

    @abc.abstractmethod
    def get_config(
        self, task_name: str, account_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        ...

    @abc.abstractmethod
    def save_config(
        self, task_name: str, account_name: str, config: Dict[str, Any]
    ) -> None:
        ...

    @abc.abstractmethod
    def delete_config(
        self, task_name: str, account_name: Optional[str] = None
    ) -> bool:
        ...

    @abc.abstractmethod
    def update_last_run(
        self, task_name: str, account_name: str, last_run: Dict[str, Any]
    ) -> None:
        ...

    @abc.abstractmethod
    def clear_last_run(self, task_name: str, account_name: str) -> None:
        ...

    @abc.abstractmethod
    def update_next_scheduled_at(
        self, task_name: str, account_name: str, next_scheduled_at: datetime | None
    ) -> None:
        ...


class DatabaseSignTaskConfigRepo(SignTaskConfigRepo):
    """基于数据库 sign_task_configs 表的存储"""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def _get_db(self):
        return self._session_factory()

    def list_configs(
        self, account_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        from backend.models.sign_task_config import SignTaskConfig

        db = self._get_db()
        try:
            q = db.query(SignTaskConfig)
            if account_name:
                q = q.filter_by(account_name=account_name)
            q = q.order_by(SignTaskConfig.account_name, SignTaskConfig.task_name)
            rows = q.all()
            return [self._row_to_dict(r) for r in rows]
        finally:
            db.close()

    def get_config(
        self, task_name: str, account_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        from backend.models.sign_task_config import SignTaskConfig

        db = self._get_db()
        try:
            q = db.query(SignTaskConfig).filter_by(task_name=task_name)
            if account_name:
                q = q.filter_by(account_name=account_name)
            row = q.first()
            return self._row_to_dict(row) if row else None
        finally:
            db.close()

    def save_config(
        self, task_name: str, account_name: str, config: Dict[str, Any]
    ) -> None:
        from backend.models.sign_task_config import SignTaskConfig

        db = self._get_db()
        try:
            row = (
                db.query(SignTaskConfig)
                .filter_by(account_name=account_name, task_name=task_name)
                .first()
            )
            payload = dict(config)
            payload.pop("account_name", None)
            sign_at = str(payload.pop("sign_at", "") or "")
            enabled = bool(payload.pop("enabled", True))
            config_json = json.dumps(payload, ensure_ascii=False)
            if row:
                row.config_json = config_json
                row.sign_at = sign_at
                row.enabled = enabled
                row.updated_at = datetime.utcnow()
            else:
                row = SignTaskConfig(
                    account_name=account_name,
                    task_name=task_name,
                    config_json=config_json,
                    sign_at=sign_at,
                    enabled=enabled,
                )
                db.add(row)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def delete_config(
        self, task_name: str, account_name: Optional[str] = None
    ) -> bool:
        from backend.models.sign_task_config import SignTaskConfig

        db = self._get_db()
        try:
            q = db.query(SignTaskConfig).filter_by(task_name=task_name)
            if account_name:
                q = q.filter_by(account_name=account_name)
            count = q.delete()
            db.commit()
            return count > 0
        except Exception:
            db.rollback()
            return False
        finally:
            db.close()

    def update_last_run(
        self, task_name: str, account_name: str, last_run: Dict[str, Any]
    ) -> None:
        from backend.models.sign_task_config import SignTaskConfig

        db = self._get_db()
        try:
            row = (
                db.query(SignTaskConfig)
                .filter_by(account_name=account_name, task_name=task_name)
                .first()
            )
            if not row:
                return
            config = json.loads(row.config_json) if row.config_json else {}
            config["last_run"] = last_run
            row.config_json = json.dumps(config, ensure_ascii=False)
            row.updated_at = datetime.utcnow()
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def clear_last_run(self, task_name: str, account_name: str) -> None:
        from backend.models.sign_task_config import SignTaskConfig

        db = self._get_db()
        try:
            row = (
                db.query(SignTaskConfig)
                .filter_by(account_name=account_name, task_name=task_name)
                .first()
            )
            if not row:
                return
            config = json.loads(row.config_json) if row.config_json else {}
            config.pop("last_run", None)
            row.config_json = json.dumps(config, ensure_ascii=False)
            row.updated_at = datetime.utcnow()
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def update_next_scheduled_at(
        self, task_name: str, account_name: str, next_scheduled_at: datetime | None
    ) -> None:
        from backend.models.sign_task_config import SignTaskConfig

        db = self._get_db()
        try:
            row = (
                db.query(SignTaskConfig)
                .filter_by(account_name=account_name, task_name=task_name)
                .first()
            )
            if not row:
                return
            row.next_scheduled_at = next_scheduled_at
            row.updated_at = datetime.utcnow()
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _row_to_dict(row) -> Dict[str, Any]:
        config = json.loads(row.config_json) if row.config_json else {}
        return {
            "name": row.task_name,
            "account_name": row.account_name,
            "sign_at": row.sign_at or "",
            "random_seconds": config.get("random_seconds", 0),
            "sign_interval": config.get("sign_interval", 1),
            "retry_count": config.get("retry_count", 0),
            "chats": config.get("chats", []),
            "enabled": row.enabled,
            "last_run": config.get("last_run"),
            "execution_mode": config.get("execution_mode", "fixed"),
            "range_start": config.get("range_start", ""),
            "range_end": config.get("range_end", ""),
            "next_scheduled_at": row.next_scheduled_at.isoformat() if row.next_scheduled_at else None,
        }


_repo: Optional[SignTaskConfigRepo] = None


def get_sign_task_config_repo() -> SignTaskConfigRepo:
    """获取 SignTask 配置存储实例（单例）"""
    global _repo
    if _repo is not None:
        return _repo

    from backend.core.database import get_session_local

    _repo = DatabaseSignTaskConfigRepo(get_session_local())
    return _repo
