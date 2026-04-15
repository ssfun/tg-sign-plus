"""
Session 存储层抽象。

当前版本仅保留数据库 Session 存储实现。
"""

from __future__ import annotations

import abc
from datetime import datetime
from typing import Any, Dict, List, Optional


class SessionStore(abc.ABC):
    """Session 存储抽象基类"""

    @abc.abstractmethod
    def list_account_names(self) -> List[str]:
        ...

    @abc.abstractmethod
    def get_session_string(self, account_name: str) -> Optional[str]:
        ...

    @abc.abstractmethod
    def set_session_string(self, account_name: str, session_string: str) -> None:
        ...

    @abc.abstractmethod
    def delete_account(self, account_name: str) -> None:
        ...

    @abc.abstractmethod
    def get_profile(self, account_name: str) -> Dict[str, Any]:
        ...

    @abc.abstractmethod
    def set_profile(
        self,
        account_name: str,
        *,
        remark: Optional[str] = None,
        proxy: Optional[str] = None,
        chat_cache_ttl_minutes: Optional[int] = None,
    ) -> None:
        ...


class DatabaseSessionStore(SessionStore):
    """基于数据库 account_sessions 表的存储实现"""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def _get_db(self):
        return self._session_factory()

    def list_account_names(self) -> List[str]:
        from backend.models.account_session import AccountSession

        db = self._get_db()
        try:
            rows = db.query(AccountSession.account_name).order_by(AccountSession.account_name).all()
            return [r[0] for r in rows]
        finally:
            db.close()

    def get_session_string(self, account_name: str) -> Optional[str]:
        from backend.models.account_session import AccountSession

        db = self._get_db()
        try:
            row = db.query(AccountSession).filter_by(account_name=account_name).first()
            if not row or not row.session_string:
                return None
            s = row.session_string.strip()
            return s or None
        finally:
            db.close()

    def set_session_string(self, account_name: str, session_string: str) -> None:
        from backend.models.account_session import AccountSession

        db = self._get_db()
        try:
            row = db.query(AccountSession).filter_by(account_name=account_name).first()
            if row:
                row.session_string = session_string.strip()
                row.updated_at = datetime.utcnow()
            else:
                row = AccountSession(
                    account_name=account_name,
                    session_string=session_string.strip(),
                )
                db.add(row)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def delete_account(self, account_name: str) -> None:
        from backend.models.account_session import AccountSession

        db = self._get_db()
        try:
            db.query(AccountSession).filter_by(account_name=account_name).delete()
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get_profile(self, account_name: str) -> Dict[str, Any]:
        from backend.models.account_session import AccountSession

        db = self._get_db()
        try:
            row = db.query(AccountSession).filter_by(account_name=account_name).first()
            if not row:
                return {}
            return {
                "remark": row.remark,
                "proxy": row.proxy,
                "chat_cache_ttl_minutes": row.chat_cache_ttl_minutes,
            }
        finally:
            db.close()

    def set_profile(
        self,
        account_name: str,
        *,
        remark: Optional[str] = None,
        proxy: Optional[str] = None,
        chat_cache_ttl_minutes: Optional[int] = None,
    ) -> None:
        from backend.models.account_session import AccountSession

        db = self._get_db()
        try:
            row = db.query(AccountSession).filter_by(account_name=account_name).first()
            if not row:
                row = AccountSession(account_name=account_name)
                db.add(row)
            if remark is not None:
                row.remark = remark.strip() if isinstance(remark, str) else remark
            if proxy is not None:
                row.proxy = proxy.strip() if isinstance(proxy, str) else proxy
            if chat_cache_ttl_minutes is not None:
                ttl = int(chat_cache_ttl_minutes)
                row.chat_cache_ttl_minutes = ttl if ttl > 0 else 1
            row.updated_at = datetime.utcnow()
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


_store: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    """获取 session 存储实例（单例）"""
    global _store
    if _store is not None:
        return _store

    from backend.core.database import get_session_local

    _store = DatabaseSessionStore(get_session_local())
    return _store
