from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import String, cast, or_

from backend.core.config import get_settings
from backend.core.database import get_session_local
from backend.models.account_chat_cache import AccountChatCacheItem, AccountChatCacheMeta
from backend.models.account_session import AccountSession
from backend.utils.account_locks import get_account_lock
from backend.utils.proxy import build_proxy_dict
from backend.utils.tg_session import (
    get_account_proxy,
    get_account_session_string,
    get_global_semaphore,
)
from tg_signer.core import get_client

settings = get_settings()


class SignTaskChatCacheService:
    def __init__(self, signs_dir: Path, account_locks: Dict[str, object]):
        self.signs_dir = signs_dir
        self._account_locks = account_locks
        self._session_factory = get_session_local()

    def _cleanup_legacy_cache_file(self, account_name: str) -> None:
        try:
            cache_file = self.signs_dir / account_name / "chats_cache.json"
            if cache_file.exists():
                cache_file.unlink()
        except Exception:
            pass

    @staticmethod
    def _is_invalid_session_error(err: Exception) -> bool:
        msg = str(err)
        if not msg:
            return False
        upper = msg.upper()
        return (
            "AUTH_KEY_UNREGISTERED" in upper
            or "AUTH_KEY_INVALID" in upper
            or "SESSION_REVOKED" in upper
            or "SESSION_EXPIRED" in upper
            or "USER_DEACTIVATED" in upper
        )

    def _get_db(self):
        return self._session_factory()

    def _resolve_cache_ttl_minutes(self, db, account_name: str) -> int:
        session_row = (
            db.query(AccountSession)
            .filter(AccountSession.account_name == account_name)
            .first()
        )
        ttl = getattr(session_row, "chat_cache_ttl_minutes", None)
        if isinstance(ttl, int) and ttl > 0:
            return ttl
        return 1440

    def _is_cache_expired(
        self, meta: AccountChatCacheMeta | None, ttl_minutes: int
    ) -> bool:
        if not meta or not meta.last_cached_at:
            return True
        ttl = ttl_minutes if ttl_minutes > 0 else 1440
        return datetime.utcnow() - meta.last_cached_at > timedelta(minutes=ttl)

    def _serialize_items(self, items: List[AccountChatCacheItem]) -> List[Dict[str, Any]]:
        return [
            {
                "id": int(item.chat_id),
                "title": item.title,
                "username": item.username,
                "type": item.chat_type,
                "first_name": item.first_name,
            }
            for item in items
        ]

    async def _cleanup_invalid_session(self, account_name: str) -> None:
        try:
            from backend.services.telegram import get_telegram_service

            await get_telegram_service().delete_account(account_name)
        except Exception:
            pass

        self._cleanup_legacy_cache_file(account_name)
        db = self._get_db()
        try:
            db.query(AccountChatCacheItem).filter(
                AccountChatCacheItem.account_name == account_name
            ).delete()
            db.query(AccountChatCacheMeta).filter(
                AccountChatCacheMeta.account_name == account_name
            ).delete()
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    def ensure_account_cache_meta(self, account_name: str) -> Dict[str, Any]:
        db = self._get_db()
        try:
            meta = (
                db.query(AccountChatCacheMeta)
                .filter(AccountChatCacheMeta.account_name == account_name)
                .first()
            )
            ttl_minutes = self._resolve_cache_ttl_minutes(db, account_name)
            if not meta:
                meta = AccountChatCacheMeta(account_name=account_name)
                db.add(meta)
                db.commit()
                db.refresh(meta)
            self._cleanup_legacy_cache_file(account_name)
            return {
                "account_name": meta.account_name,
                "cache_ttl_minutes": ttl_minutes,
                "last_cached_at": meta.last_cached_at.isoformat() + "Z" if meta.last_cached_at else None,
                "expired": self._is_cache_expired(meta, ttl_minutes),
                "count": db.query(AccountChatCacheItem)
                .filter(AccountChatCacheItem.account_name == account_name)
                .count(),
            }
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get_account_chat_cache(self, account_name: str) -> Dict[str, Any]:
        db = self._get_db()
        try:
            meta = (
                db.query(AccountChatCacheMeta)
                .filter(AccountChatCacheMeta.account_name == account_name)
                .first()
            )
            items = (
                db.query(AccountChatCacheItem)
                .filter(AccountChatCacheItem.account_name == account_name)
                .order_by(AccountChatCacheItem.title.asc(), AccountChatCacheItem.chat_id.asc())
                .all()
            )
            ttl = self._resolve_cache_ttl_minutes(db, account_name)
            last_cached_at = meta.last_cached_at if meta else None
            expired = self._is_cache_expired(meta, ttl)
            self._cleanup_legacy_cache_file(account_name)
            return {
                "items": self._serialize_items(items),
                "last_cached_at": last_cached_at.isoformat() + "Z" if last_cached_at else None,
                "cache_ttl_minutes": ttl,
                "expired": expired,
                "count": len(items),
            }
        finally:
            db.close()

    async def get_account_chats(
        self,
        account_name: str,
        force_refresh: bool = False,
        *,
        auto_refresh_if_expired: bool = False,
        ensure_exists: bool = False,
    ) -> Dict[str, Any]:
        cache = self.get_account_chat_cache(account_name)
        should_refresh = force_refresh
        if ensure_exists and cache["count"] == 0:
            should_refresh = True
        if auto_refresh_if_expired and cache["expired"]:
            should_refresh = True

        if not should_refresh:
            return cache

        account_lock = get_account_lock(account_name)
        if account_lock.locked():
            if force_refresh:
                raise RuntimeError("账号当前正在执行任务，暂时无法刷新聊天列表，请稍后再试")
            return cache

        items = await self.refresh_account_chats(account_name)
        refreshed = self.get_account_chat_cache(account_name)
        refreshed["items"] = items
        refreshed["count"] = len(items)
        refreshed["expired"] = False
        return refreshed

    def search_account_chats(
        self,
        account_name: str,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        if limit < 1:
            limit = 1
        if limit > 200:
            limit = 200
        if offset < 0:
            offset = 0

        q = (query or "").strip()

        db = self._get_db()
        try:
            base_query = db.query(AccountChatCacheItem).filter(
                AccountChatCacheItem.account_name == account_name
            )

            if q:
                is_numeric = q.lstrip("-").isdigit() or q.startswith("-100")
                if is_numeric:
                    base_query = base_query.filter(
                        cast(AccountChatCacheItem.chat_id, String).contains(q)
                    )
                else:
                    like_query = f"%{q}%"
                    base_query = base_query.filter(
                        or_(
                            AccountChatCacheItem.title.ilike(like_query),
                            AccountChatCacheItem.username.ilike(like_query),
                            AccountChatCacheItem.first_name.ilike(like_query),
                        )
                    )

            total = base_query.count()
            rows = (
                base_query.order_by(
                    AccountChatCacheItem.title.asc(),
                    AccountChatCacheItem.chat_id.asc(),
                )
                .offset(offset)
                .limit(limit)
                .all()
            )
            return {
                "items": self._serialize_items(rows),
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        finally:
            db.close()

    async def refresh_account_chats(self, account_name: str) -> List[Dict[str, Any]]:
        from pyrogram.enums import ChatType
        from backend.services.config import get_config_service

        session_dir = settings.resolve_session_dir()
        session_string = get_account_session_string(account_name)
        if not session_string:
            raise ValueError(f"账号 {account_name} 登录已失效，请重新登录")

        config_service = get_config_service()
        tg_config = config_service.get_telegram_config()
        api_id = os.getenv("TG_API_ID") or tg_config.get("api_id")
        api_hash = os.getenv("TG_API_HASH") or tg_config.get("api_hash")

        try:
            api_id = int(api_id) if api_id is not None else None
        except (TypeError, ValueError):
            api_id = None

        if isinstance(api_hash, str):
            api_hash = api_hash.strip()

        if not api_id or not api_hash:
            raise ValueError("未配置 Telegram API ID 或 API Hash")

        proxy_dict = None
        proxy_value = get_account_proxy(account_name)
        if proxy_value:
            proxy_dict = build_proxy_dict(proxy_value)
        client_kwargs = {
            "name": account_name,
            "workdir": session_dir,
            "api_id": api_id,
            "api_hash": api_hash,
            "session_string": session_string,
            "in_memory": True,
            "proxy": proxy_dict,
            "no_updates": True,
        }
        client = get_client(**client_kwargs)

        chats: List[Dict[str, Any]] = []
        logger = logging.getLogger("backend")
        try:
            if account_name not in self._account_locks:
                self._account_locks[account_name] = get_account_lock(account_name)

            account_lock = self._account_locks[account_name]

            async def _fetch_chats(active_client) -> List[Dict[str, Any]]:
                local_chats: List[Dict[str, Any]] = []
                async with account_lock:
                    async with get_global_semaphore():
                        async with active_client:
                            await active_client.get_me()
                            try:
                                async for dialog in active_client.get_dialogs():
                                    try:
                                        chat = getattr(dialog, "chat", None)
                                        if chat is None:
                                            logger.warning("get_dialogs 返回空 chat，已跳过")
                                            continue
                                        chat_id = getattr(chat, "id", None)
                                        if chat_id is None:
                                            logger.warning("get_dialogs 返回 chat.id 为空，已跳过")
                                            continue

                                        chat_info = {
                                            "id": chat_id,
                                            "title": chat.title
                                            or chat.first_name
                                            or chat.username
                                            or str(chat_id),
                                            "username": chat.username,
                                            "type": chat.type.name.lower(),
                                            "first_name": getattr(chat, "first_name", None),
                                        }
                                        if chat.type == ChatType.BOT:
                                            chat_info["title"] = f"🤖 {chat_info['title']}"
                                        local_chats.append(chat_info)
                                    except Exception as e:
                                        logger.warning(
                                            f"处理 dialog 失败，已跳过: {type(e).__name__}: {e}"
                                        )
                                        continue
                            except Exception as e:
                                logger.warning(
                                    f"get_dialogs 中断，返回已获取结果: {type(e).__name__}: {e}"
                                )
                return local_chats

            try:
                chats = await _fetch_chats(client)
            except Exception as e:
                if self._is_invalid_session_error(e):
                    logger.warning("Session invalid for %s: %s", account_name, e)
                    await self._cleanup_invalid_session(account_name)
                    raise ValueError(f"账号 {account_name} 登录已失效，请重新登录")
                raise

            deduped_chats: List[Dict[str, Any]] = []
            seen_chat_ids: set[int] = set()
            duplicate_chat_count = 0
            for chat in chats:
                chat_id = chat.get("id")
                if chat_id is None:
                    continue
                normalized_chat_id = int(chat_id)
                if normalized_chat_id in seen_chat_ids:
                    duplicate_chat_count += 1
                    continue
                seen_chat_ids.add(normalized_chat_id)
                if normalized_chat_id != chat_id:
                    chat = {**chat, "id": normalized_chat_id}
                deduped_chats.append(chat)
            if duplicate_chat_count:
                logger.warning(
                    "Account %s chat cache refresh skipped %s duplicate dialogs",
                    account_name,
                    duplicate_chat_count,
                )
            chats = deduped_chats

            now = datetime.utcnow()
            db = self._get_db()

            try:
                meta = (
                    db.query(AccountChatCacheMeta)
                    .filter(AccountChatCacheMeta.account_name == account_name)
                    .first()
                )
                if not meta:
                    meta = AccountChatCacheMeta(account_name=account_name)
                    db.add(meta)
                meta.last_cached_at = now
                meta.last_refresh_status = "success"
                meta.last_refresh_error = None
                meta.updated_at = now

                db.query(AccountChatCacheItem).filter(
                    AccountChatCacheItem.account_name == account_name
                ).delete()
                for chat in chats:
                    db.add(
                        AccountChatCacheItem(
                            account_name=account_name,
                            chat_id=int(chat["id"]),
                            title=chat.get("title"),
                            username=chat.get("username"),
                            chat_type=chat.get("type") or "unknown",
                            first_name=chat.get("first_name"),
                            cached_at=now,
                        )
                    )
                db.commit()
                self._cleanup_legacy_cache_file(account_name)
            except Exception as db_err:
                db.rollback()
                meta = (
                    db.query(AccountChatCacheMeta)
                    .filter(AccountChatCacheMeta.account_name == account_name)
                    .first()
                )
                if not meta:
                    meta = AccountChatCacheMeta(account_name=account_name)
                    db.add(meta)
                meta.last_refresh_status = "failed"
                meta.last_refresh_error = str(db_err)
                meta.updated_at = now
                db.commit()
                raise
            finally:
                db.close()

            return chats
        except Exception:
            raise
