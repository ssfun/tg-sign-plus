from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

from backend.utils.session_store import get_session_store

_GLOBAL_SEMAPHORE: Optional[asyncio.Semaphore] = None


def get_no_updates_flag() -> bool:
    raw = os.getenv("TG_SESSION_NO_UPDATES") or os.getenv("TG_NO_UPDATES") or ""
    raw = raw.strip().lower()
    return raw in {"1", "true", "yes", "on"}


def get_global_semaphore() -> asyncio.Semaphore:
    global _GLOBAL_SEMAPHORE
    if _GLOBAL_SEMAPHORE is None:
        raw = (os.getenv("TG_GLOBAL_CONCURRENCY") or "1").strip()
        try:
            limit = int(raw)
        except ValueError:
            limit = 1
        if limit < 1:
            limit = 1
        _GLOBAL_SEMAPHORE = asyncio.Semaphore(limit)
    return _GLOBAL_SEMAPHORE


# ---- 以下函数委托给 SessionStore ----


def list_account_names() -> list[str]:
    return get_session_store().list_account_names()


def get_account_session_string(account_name: str) -> Optional[str]:
    return get_session_store().get_session_string(account_name)


def set_account_session_string(account_name: str, session_string: str) -> None:
    get_session_store().set_session_string(account_name, session_string)


def delete_account_session_string(account_name: str) -> None:
    get_session_store().delete_account(account_name)


def get_account_profile(account_name: str) -> dict[str, Any]:
    return get_session_store().get_profile(account_name)


def get_account_proxy(account_name: str) -> Optional[str]:
    profile = get_account_profile(account_name)
    proxy = profile.get("proxy")
    if isinstance(proxy, str) and proxy.strip():
        return proxy.strip()
    return None


def get_account_remark(account_name: str) -> Optional[str]:
    profile = get_account_profile(account_name)
    remark = profile.get("remark")
    if isinstance(remark, str) and remark.strip():
        return remark.strip()
    return None


def set_account_profile(
    account_name: str,
    *,
    remark: Optional[str] = None,
    proxy: Optional[str] = None,
    chat_cache_ttl_minutes: Optional[int] = None,
) -> None:
    get_session_store().set_profile(
        account_name,
        remark=remark,
        proxy=proxy,
        chat_cache_ttl_minutes=chat_cache_ttl_minutes,
    )

