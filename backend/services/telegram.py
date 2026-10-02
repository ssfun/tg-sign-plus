"""
Telegram 服务层
提供 Telegram 账号管理和操作的核心功能
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import logging
import os
import secrets
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.core.config import get_settings
from backend.models.account_chat_cache import AccountChatCacheItem, AccountChatCacheMeta
from backend.utils.account_locks import get_account_lock
from backend.utils.proxy import build_proxy_dict
from backend.utils.tg_session import (
    delete_account_session_string,
    get_account_profile,
    get_account_session_string,
    get_global_semaphore,
    list_account_names,
    list_account_profiles,
    set_account_session_string,
)

settings = get_settings()
logger = logging.getLogger("backend.qr_login")

# 全局存储临时的登录 session
_login_sessions = {}
_qr_login_sessions = {}


class TelegramService:
    """Telegram 服务类"""

    def __init__(self):
        self.session_dir = settings.resolve_session_dir()
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._accounts_cache: Optional[List[Dict[str, Any]]] = None

    def list_accounts(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        获取所有账号列表（基于数据库 session 存储）

        Returns:
            账号列表，每个账号包含：
            - name: 账号名称
            - session_file: 会话存储标识（兼容现有前端字段）
            - exists: 账号是否存在
            - size: 占位字段
        """
        if self._accounts_cache is not None and not force_refresh:
            return self._accounts_cache

        accounts = []

        pending_accounts = set()
        for data in _login_sessions.values():
            name = data.get("account_name")
            if name:
                pending_accounts.add(name)
        for data in _qr_login_sessions.values():
            name = data.get("account_name")
            status = data.get("status")
            if name and status != "success":
                pending_accounts.add(name)

        try:
            for profile in list_account_profiles():
                account_name = profile["account_name"]
                if account_name in pending_accounts:
                    continue
                accounts.append(
                    {
                        "name": account_name,
                        "session_file": f"db://account_sessions/{account_name}",
                        "exists": True,
                        "size": 0,
                        "remark": profile.get("remark"),
                        "proxy": profile.get("proxy"),
                        "chat_cache_ttl_minutes": profile.get("chat_cache_ttl_minutes") or 1440,
                    }
                )

            self._accounts_cache = sorted(accounts, key=lambda x: x["name"])
            return self._accounts_cache
        except Exception as e:
            import logging
            logger = logging.getLogger("backend.telegram")
            logger.error(f"获取账号列表失败: {e}", exc_info=True)
            return []

    @staticmethod
    def _normalize_login_token_expires(expires: Optional[int]) -> int:
        now = int(time.time())
        if not expires:
            return now + 300
        try:
            expires_int = int(expires)
        except (TypeError, ValueError):
            return now + 300
        # 兼容 expires 为相对秒数的情况
        if expires_int < 1_000_000_000:
            expires_ts = now + max(0, expires_int)
        else:
            expires_ts = expires_int
        if expires_ts <= now + 5:
            return now + 300
        return expires_ts

    def account_exists(self, account_name: str) -> bool:
        """检查账号是否存在"""
        if self._accounts_cache is not None:
            for acc in self._accounts_cache:
                if acc["name"] == account_name:
                    return True

        return bool(get_account_session_string(account_name))

    async def check_account_status(
        self, account_name: str, timeout_seconds: float = 8.0
    ) -> Dict[str, Any]:
        """
        检测账号 session 是否可用。

        设计目标：
        1. 使用独立临时 Client，不影响正在运行中的任务连接。
        2. 使用单次 get_me 探活，避免执行重操作。
        3. 将“会话失效”与“临时网络错误”分开，前端可据此决定是否引导重新登录。
        """
        from pyrogram import Client
        from tg_signer.client_manager import get_api_config, get_proxy

        checked_at = datetime.utcnow().isoformat() + "Z"

        if not self.account_exists(account_name):
            return {
                "account_name": account_name,
                "ok": False,
                "status": "not_found",
                "message": "账号不存在",
                "code": "ACCOUNT_NOT_FOUND",
                "checked_at": checked_at,
                "needs_relogin": True,
            }

        proxy_dict = None
        try:
            profile = get_account_profile(account_name) or {}
            proxy_value = profile.get("proxy")
            if proxy_value:
                proxy_dict = build_proxy_dict(proxy_value)
        except Exception:
            proxy_dict = None

        session_string = get_account_session_string(account_name)
        if not session_string:
            return {
                "account_name": account_name,
                "ok": False,
                "status": "invalid",
                "message": "session_string 不存在或已失效",
                "code": "ACCOUNT_SESSION_INVALID",
                "checked_at": checked_at,
                "needs_relogin": True,
            }

        timeout_seconds = max(1.0, min(float(timeout_seconds or 8.0), 20.0))

        async def probe():
            async with get_account_lock(account_name):
                async with get_global_semaphore():
                    api_id, api_hash = get_api_config()
                    client = Client(
                        name=account_name, api_id=api_id, api_hash=api_hash,
                        proxy=proxy_dict or get_proxy(), workdir=self.session_dir,
                        session_string=session_string, in_memory=True, no_updates=True,
                    )
                    try:
                        await client.connect()
                        return await client.get_me()
                    finally:
                        await self._close_temporary_client(client)

        try:
            me = await asyncio.wait_for(probe(), timeout=timeout_seconds)
            return {
                "account_name": account_name,
                "ok": True,
                "status": "connected",
                "message": "",
                "code": "OK",
                "checked_at": checked_at,
                "needs_relogin": False,
                "user_id": getattr(me, "id", None),
            }
        except asyncio.TimeoutError:
            return {
                "account_name": account_name,
                "ok": False,
                "status": "checking",
                "message": "Request timed out",
                "code": "TIMEOUT",
                "checked_at": checked_at,
                "needs_relogin": False,
            }
        except ConnectionError as e:
            return {
                "account_name": account_name,
                "ok": False,
                "status": "checking",
                "message": str(e),
                "code": "CONNECTION_ERROR",
                "checked_at": checked_at,
                "needs_relogin": False,
            }
        except Exception as e:
            err_text = str(e) or type(e).__name__
            err_upper = err_text.upper()
            err_lower = err_text.lower()
            if (
                "READONLY DATABASE" in err_upper
                or "PERMISSION DENIED" in err_upper
                or "ATTEMPT TO WRITE A READONLY DATABASE" in err_upper
            ):
                return {
                    "account_name": account_name,
                    "ok": False,
                    "status": "checking",
                    "message": err_text,
                    "code": "STORAGE_PERMISSION_DENIED",
                    "checked_at": checked_at,
                    "needs_relogin": False,
                }
            if "SESSION" in err_upper and "INVALID" in err_upper:
                return {
                    "account_name": account_name,
                    "ok": False,
                    "status": "invalid",
                    "message": err_text,
                    "code": "ACCOUNT_SESSION_INVALID",
                    "checked_at": checked_at,
                    "needs_relogin": True,
                }
            if "UNAUTHORIZED" in err_upper or "AUTH_KEY_UNREGISTERED" in err_upper:
                return {
                    "account_name": account_name,
                    "ok": False,
                    "status": "invalid",
                    "message": err_text,
                    "code": "ACCOUNT_SESSION_INVALID",
                    "checked_at": checked_at,
                    "needs_relogin": True,
                }
            if "FLOOD_WAIT" in err_upper or "TRANSPORT FLOOD" in err_lower:
                return {
                    "account_name": account_name,
                    "ok": False,
                    "status": "checking",
                    "message": err_text,
                    "code": "FLOOD_WAIT",
                    "checked_at": checked_at,
                    "needs_relogin": False,
                }
            if (
                "TIMEOUT" in err_upper
                or "TIMED OUT" in err_upper
                or "REQUEST TIMED OUT" in err_upper
                or "REQUEST TIME OUT" in err_upper
            ):
                return {
                    "account_name": account_name,
                    "ok": False,
                    "status": "checking",
                    "message": err_text,
                    "code": "TIMEOUT",
                    "checked_at": checked_at,
                    "needs_relogin": False,
                }
            if (
                "CONNECTION" in err_upper
                or "NETWORK" in err_upper
                or "CONNECTION RESET" in err_upper
                or "BROKEN PIPE" in err_upper
            ):
                return {
                    "account_name": account_name,
                    "ok": False,
                    "status": "checking",
                    "message": err_text,
                    "code": "CONNECTION_ERROR",
                    "checked_at": checked_at,
                    "needs_relogin": False,
                }
            return {
                "account_name": account_name,
                "ok": False,
                "status": "error",
                "message": err_text,
                "code": type(e).__name__.upper(),
                "checked_at": checked_at,
                "needs_relogin": False,
            }

    async def delete_account(self, account_name: str) -> bool:
        """
        删除账号。

        Args:
            account_name: 账号名称

        Returns:
            是否成功删除
        """
        # 确保释放资源
        from tg_signer.client_manager import close_client_by_name

        # 尝试关闭 active client
        try:
            await close_client_by_name(account_name, workdir=self.session_dir)
        except Exception:
            pass

        has_session_string = bool(get_account_session_string(account_name))
        account_in_store = account_name in list_account_names()

        if not (has_session_string or account_in_store):
            return False

        delete_account_session_string(account_name)
        try:
            from backend.services.sign_tasks import get_sign_task_service

            chat_service = get_sign_task_service().chat_cache_service
            db = chat_service._get_db()
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
        except Exception:
            pass

        if self._accounts_cache is not None:
            self._accounts_cache = [
                acc for acc in self._accounts_cache if acc["name"] != account_name
            ]

        return True

    @staticmethod
    async def _close_temporary_client(client) -> None:
        """Finish bounded teardown before propagating caller cancellation."""
        from tg_signer.client_manager import _await_cleanup_step

        async def close_step(call):
            try:
                result = call()
                if inspect.isawaitable(result):
                    await _await_cleanup_step(result, timeout=3)
                return True
            except (Exception, asyncio.CancelledError):
                logger.warning("Failed to close temporary Telegram client", exc_info=True)
                return False

        async def close_transport(session):
            # Kurigram stop() returns early in STOPPING after a cancelled stop.
            # Close the captured transport even when another stop reports success.
            connection = getattr(session, "connection", None)
            closed = False
            if connection and getattr(connection, "close", None):
                closed = await close_step(connection.close)
            tasks = set(getattr(session, "pending_tasks", ()))
            tasks.update(getattr(session, name, None) for name in ("ping_task", "recv_task"))
            tasks.discard(None)
            tasks.discard(asyncio.current_task())
            for task in tasks:
                task.cancel()
            if tasks:
                async def drain():
                    await asyncio.gather(*tasks, return_exceptions=True)
                await close_step(drain)
            return closed

        async def cleanup():
            # disconnect() clears client.session; retain ownership until teardown ends.
            primary = getattr(client, "session", None)
            sessions = getattr(client, "sessions", {})
            for session in list(sessions.values()):
                await close_step(session.stop)
                await close_transport(session)
            sessions.clear()
            close = client.stop if getattr(client, "is_initialized", False) else client.disconnect
            closed = await close_step(close)
            if not closed and primary and getattr(primary, "stop", None):
                await close_step(primary.stop)
            if primary and await close_transport(primary):
                client.is_connected = False
            if not closed:
                storage = getattr(client, "storage", None)
                if storage and getattr(storage, "close", None):
                    await close_step(storage.close)

        pending = asyncio.create_task(cleanup())
        cancelled = None
        while not pending.done():
            try:
                await asyncio.shield(pending)
            except asyncio.CancelledError as exc:
                cancelled = exc
        pending.result()
        if cancelled is not None:
            raise cancelled

    @staticmethod
    def _login_seconds(name: str, default: int) -> int:
        try:
            return max(1, int(os.getenv(name, str(default))))
        except ValueError:
            return default

    async def _cleanup_phone_login(self, key: str, data: dict) -> bool:
        if _login_sessions.get(key) is not data:
            return False
        _login_sessions.pop(key)
        timer = data.get("expiry_task")
        if timer and timer is not asyncio.current_task():
            timer.cancel()
        await self._close_temporary_client(data["client"])
        self._accounts_cache = None
        return True

    async def _expire_phone_login(self, key: str, data: dict) -> None:
        try:
            while _login_sessions.get(key) is data:
                await asyncio.sleep(max(0, data["expires_at"] - time.monotonic()))
                async with get_account_lock(data["account_name"]):
                    if data["expires_at"] <= time.monotonic():
                        await self._cleanup_phone_login(key, data)
                        return
        except asyncio.CancelledError:
            return

    async def cancel_phone_login(self, account_name: str, phone_number: str, phone_code_hash: str) -> bool:
        async def cancel():
            async with get_account_lock(account_name):
                key = f"{account_name}_{phone_number}"
                data = _login_sessions.get(key)
                if not data or data.get("phone_code_hash") != phone_code_hash:
                    return False
                return await self._cleanup_phone_login(key, data)
        return await asyncio.wait_for(cancel(), timeout=self._login_seconds("TG_LOGIN_TIMEOUT", 30))

    async def close_pending_logins(self) -> None:
        for key, data in list(_login_sessions.items()):
            async with get_account_lock(data["account_name"]):
                await self._cleanup_phone_login(key, data)
        for login_id in list(_qr_login_sessions):
            await self._cleanup_qr_login(login_id)

    async def start_login(
        self, account_name: str, phone_number: str, proxy: Optional[str] = None,
        chat_cache_ttl_minutes: Optional[int] = None,
    ) -> Dict[str, Any]:
        from pyrogram import Client
        from pyrogram.errors import FloodWait, PhoneNumberInvalid
        from backend.services.config import get_config_service

        config = get_config_service().get_telegram_config()
        try:
            api_id = int(os.getenv("TG_API_ID") or config.get("api_id") or 0)
        except (TypeError, ValueError):
            api_id = 0
        api_hash = str(os.getenv("TG_API_HASH") or config.get("api_hash") or "").strip()
        if not api_id or not api_hash:
            raise ValueError("Telegram API ID / API Hash 未配置或无效")
        proxy_dict = build_proxy_dict(proxy) if proxy else None

        async def start():
            async with get_account_lock(account_name):
                # No execution lock is held while the user is entering an OTP.
                # All mutations/verification/cancellation of this session use it.
                for key, old in list(_login_sessions.items()):
                    if old.get("account_name") == account_name:
                        await self._cleanup_phone_login(key, old)
                client = Client(
                    name=str(self.session_dir / account_name), api_id=api_id, api_hash=api_hash,
                    proxy=proxy_dict, in_memory=True, no_updates=True,
                )
                retained = False
                try:
                    async with get_global_semaphore():
                        await client.connect()
                        sent_code = await client.send_code(phone_number)
                    key = f"{account_name}_{phone_number}"
                    data = {
                        "client": client, "phone_code_hash": sent_code.phone_code_hash,
                        "phone_number": phone_number, "account_name": account_name, "proxy": proxy,
                        "chat_cache_ttl_minutes": chat_cache_ttl_minutes,
                        "expires_at": time.monotonic() + self._login_seconds("TG_PHONE_LOGIN_TTL", 300),
                    }
                    _login_sessions[key] = data
                    data["expiry_task"] = asyncio.create_task(self._expire_phone_login(key, data))
                    retained = True
                    self._accounts_cache = None
                    return {"phone_code_hash": sent_code.phone_code_hash, "phone_number": phone_number, "account_name": account_name}
                finally:
                    if not retained:
                        await self._close_temporary_client(client)
        try:
            return await asyncio.wait_for(start(), timeout=self._login_seconds("TG_LOGIN_TIMEOUT", 30))
        except PhoneNumberInvalid:
            raise ValueError("手机号格式无效，请使用国际格式（如 +8613800138000）")
        except FloodWait as exc:
            raise ValueError(f"请求过于频繁，请等待 {exc.value} 秒后重试")
        except asyncio.TimeoutError:
            raise ValueError("发送验证码超时，请稍后重试")
        except Exception as exc:
            raise ValueError(f"发送验证码失败: {exc}") from exc

    async def verify_login(
        self, account_name: str, phone_number: str, phone_code: str, phone_code_hash: str,
        password: Optional[str] = None, proxy: Optional[str] = None,
        chat_cache_ttl_minutes: Optional[int] = None,
    ) -> Dict[str, Any]:
        from pyrogram.errors import PasswordHashInvalid, PhoneCodeExpired, PhoneCodeInvalid, SessionPasswordNeeded
        from backend.utils.tg_session import set_account_profile

        async def verify():
            async with get_account_lock(account_name):
                key = f"{account_name}_{phone_number}"
                data = _login_sessions.get(key)
                if not data or (data.get("phone_code_hash") and data["phone_code_hash"] != phone_code_hash):
                    raise ValueError("登录会话已过期，请重新发送验证码")
                if data.get("expires_at", float("inf")) <= time.monotonic():
                    await self._cleanup_phone_login(key, data)
                    raise ValueError("登录会话已过期，请重新发送验证码")
                client = data["client"]
                keep_for_password = False
                try:
                    async with get_global_semaphore():
                        if not client.is_connected:
                            await client.connect()
                        try:
                            await client.sign_in(phone_number, phone_code_hash, phone_code.strip().replace(" ", "").replace("-", ""))
                        except SessionPasswordNeeded:
                            keep_for_password = True
                            if not password:
                                raise ValueError("此账号启用了两步验证，请输入 2FA 密码")
                            try:
                                await client.check_password(password)
                            except PasswordHashInvalid:
                                raise ValueError("2FA 密码错误")
                            keep_for_password = False
                        me = await client.get_me()
                        session_string = await client.export_session_string()
                        if not session_string:
                            raise ValueError("导出 session_string 失败")
                        set_account_session_string(account_name, session_string)
                        set_account_profile(
                            account_name,
                            proxy=proxy if proxy is not None else data.get("proxy"),
                            chat_cache_ttl_minutes=chat_cache_ttl_minutes if chat_cache_ttl_minutes is not None else data.get("chat_cache_ttl_minutes"),
                        )
                        # Pending probes/tasks must not reuse an old authorized client.
                        from tg_signer.client_manager import close_client_by_name
                        await close_client_by_name(account_name, workdir=self.session_dir)
                        from backend.services.sign_tasks import get_sign_task_service
                        get_sign_task_service().ensure_account_chat_cache_meta(account_name)
                        return {"success": True, "user_id": me.id, "first_name": me.first_name, "username": me.username}
                except PhoneCodeInvalid:
                    raise ValueError("验证码错误，请检查验证码是否正确")
                except PhoneCodeExpired:
                    raise ValueError("验证码已过期，请重新获取")
                except asyncio.CancelledError:
                    keep_for_password = False
                    raise
                finally:
                    if keep_for_password:
                        data["expires_at"] = time.monotonic() + self._login_seconds("TG_PHONE_LOGIN_TTL", 300)
                    else:
                        await self._cleanup_phone_login(key, data)
        try:
            return await asyncio.wait_for(verify(), timeout=self._login_seconds("TG_LOGIN_TIMEOUT", 30))
        except asyncio.TimeoutError:
            raise ValueError("登录验证超时，请重新发送验证码")

    async def _persist_client_session(
        self,
        client,
        account_name: str,
        proxy: Optional[str] = None,
        chat_cache_ttl_minutes: Optional[int] = None,
    ) -> None:
        session_string = await client.export_session_string()
        if not session_string:
            raise ValueError("导出 session_string 失败")
        set_account_session_string(account_name, session_string)
        from backend.utils.tg_session import set_account_profile

        set_account_profile(
            account_name,
            proxy=proxy,
            chat_cache_ttl_minutes=chat_cache_ttl_minutes,
        )
        try:
            from backend.services.sign_tasks import get_sign_task_service

            get_sign_task_service().ensure_account_chat_cache_meta(account_name)
            # Chat lists load on demand in the task page, after login releases its locks.
        except Exception:
            pass
        self._accounts_cache = None

    def _log_qr_state(
        self, login_id: str, state: str, data: Optional[Dict[str, Any]] = None
    ) -> None:
        if not login_id:
            return
        if data is not None:
            last_state = data.get("last_state_logged")
            if last_state == state:
                return
            data["last_state_logged"] = state
        logger.info("qr_login state=%s login_id=%s", state, login_id)

    @staticmethod
    async def _parse_login_user(client, user):
        from pyrogram import types

        # Kurigram 2.2.x contains both synchronous and asynchronous parsers.
        parsed = types.User._parse(client, user)
        return await parsed if inspect.isawaitable(parsed) else parsed

    async def _apply_migrate_auth(self, client, data: Dict[str, Any]) -> None:
        migrate_dc_id = data.get("migrate_dc_id")
        migrate_auth_key = data.get("migrate_auth_key")
        if migrate_dc_id and migrate_auth_key:
            try:
                await client.storage.dc_id(migrate_dc_id)
                await client.storage.auth_key(migrate_auth_key)
            except Exception:
                pass

    @staticmethod
    def _capture_migrate_auth(data: Dict[str, Any], session: Any) -> None:
        if not session:
            return
        try:
            auth_key = getattr(session, "auth_key", None)
            dc_id = getattr(session, "dc_id", None)
            if auth_key:
                data["migrate_auth_key"] = auth_key
            if dc_id:
                data["migrate_dc_id"] = dc_id
        except Exception:
            pass

    async def _cleanup_qr_login(self, login_id: str, preserve_session: bool = False) -> None:
        data = _qr_login_sessions.pop(login_id, None)
        if not data:
            return
        timer = data.get("expiry_task")
        if timer and timer is not asyncio.current_task():
            timer.cancel()
        client = data.get("client")
        handler = data.get("handler")
        if client and handler:
            try:
                client.remove_handler(*handler)
            except Exception:
                pass
        if client:
            # Kurigram stop/disconnect does not close non-media DC sessions.
            # Close these before the primary connection and storage are shut down.
            sessions = getattr(client, "sessions", {})
            for session in list(sessions.values()):
                try:
                    await session.stop()
                except Exception:
                    logger.warning("Failed to close QR login DC session", exc_info=True)
            sessions.clear()
            try:
                if getattr(client, "is_initialized", False):
                    await client.stop()
                elif getattr(client, "is_connected", False):
                    await client.disconnect()
            except Exception:
                try:
                    if getattr(client, "is_connected", False):
                        await client.disconnect()
                except Exception:
                    pass
        if not preserve_session:
            account_name = data.get("account_name")
            if account_name:
                delete_account_session_string(account_name)
                self._accounts_cache = None
        lock = data.get("lock")
        if lock and lock.locked():
            lock.release()

    def _extend_qr_expires(self, data: Dict[str, Any], min_seconds: int = 300) -> None:
        now = int(time.time())
        min_expires = now + min_seconds
        current = int(data.get("expires_ts") or 0)
        if current < min_expires:
            data["expires_ts"] = min_expires
            data["expires_at"] = datetime.utcfromtimestamp(min_expires).isoformat() + "Z"

    async def _expire_qr_login(self, login_id: str, expires_ts: int) -> None:
        while True:
            wait_seconds = max(0, int(expires_ts - time.time()))
            if wait_seconds:
                await asyncio.sleep(wait_seconds)
            data = _qr_login_sessions.get(login_id)
            if not data:
                return
            current_expires = int(data.get("expires_ts") or 0)
            if current_expires > expires_ts:
                expires_ts = current_expires
                continue
            data["status"] = "expired"
            self._log_qr_state(login_id, "expired", data)
            await self._cleanup_qr_login(login_id)
            return

    async def start_qr_login(
        self,
        account_name: str,
        proxy: Optional[str] = None,
        chat_cache_ttl_minutes: Optional[int] = None,
    ) -> Dict[str, Any]:
        import gc

        from pyrogram import Client, handlers, raw
        from pyrogram.errors import FloodWait

        from tg_signer.client_manager import close_client_by_name

        account_lock = get_account_lock(account_name)
        global_semaphore = get_global_semaphore()

        # 清理同账号残留的扫码会话
        for key, value in list(_qr_login_sessions.items()):
            if value.get("account_name") == account_name:
                await self._cleanup_qr_login(key)

        await account_lock.acquire()

        def _release_account_lock() -> None:
            if account_lock.locked():
                account_lock.release()

        # 清理后台客户端
        try:
            await close_client_by_name(account_name, workdir=self.session_dir)
        except Exception:
            pass

        gc.collect()

        # API credentials
        from backend.services.config import get_config_service

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
            _release_account_lock()
            raise ValueError("Telegram API ID / API Hash 未配置或无效")

        proxy_dict = build_proxy_dict(proxy) if proxy else None

        session_path = str(self.session_dir / account_name)
        client_kwargs = {
            "name": session_path,
            "api_id": api_id,
            "api_hash": api_hash,
            "proxy": proxy_dict,
            "in_memory": True,
        }
        # QR 登录依赖 UpdateLoginToken，必须启用 updates
        client_kwargs["no_updates"] = False
        client = Client(**client_kwargs)

        try:
            async with global_semaphore:
                await client.connect()

                if hasattr(client, "storage") and getattr(client.storage, "conn", None):
                    try:
                        client.storage.conn.execute("PRAGMA journal_mode=WAL")
                        client.storage.conn.execute("PRAGMA busy_timeout=30000")
                    except Exception:
                        pass

                result = await client.invoke(
                    raw.functions.auth.ExportLoginToken(
                        api_id=api_id, api_hash=api_hash, except_ids=[]
                    )
                )

            token_bytes = getattr(result, "token", None)
            if not token_bytes:
                raise ValueError("获取二维码 token 失败")

            token_expires = getattr(result, "expires", None)
            expires_ts = self._normalize_login_token_expires(token_expires)
            expires_at = datetime.utcfromtimestamp(expires_ts).isoformat() + "Z"
            qr_uri = "tg://login?token=" + base64.urlsafe_b64encode(
                token_bytes
            ).decode("utf-8")

            login_id = secrets.token_urlsafe(16)

            session_data = {
                "account_name": account_name,
                "proxy": proxy,
                "chat_cache_ttl_minutes": chat_cache_ttl_minutes,
                "client": client,
                "token": token_bytes,
                "expires_ts": expires_ts,
                "expires_at": expires_at,
                "status": "waiting_scan",
                "scan_seen": False,
                "lock": account_lock,
                "migrate_dc_id": getattr(result, "dc_id", None),
                "api_id": api_id,
                "api_hash": api_hash,
                "handler": None,
            }
            _qr_login_sessions[login_id] = session_data
            self._log_qr_state(login_id, "waiting_scan", session_data)

            # 监听扫码更新
            try:
                # 初始化 updates/dispatcher，确保后续 stop 能完整关闭
                try:
                    if not getattr(client, "is_initialized", False):
                        await client.initialize()
                except Exception:
                    try:
                        await client.dispatcher.start()
                    except Exception:
                        pass

                async def _raw_handler(_, update, __, ___):
                    if not isinstance(update, raw.types.UpdateLoginToken):
                        return
                    data = _qr_login_sessions.get(login_id)
                    if data and data.get("status") in ("waiting_scan", "scanned_wait_confirm"):
                        new_token = getattr(update, "token", None)
                        if new_token:
                            data["token"] = new_token
                        token_expires = getattr(update, "expires", None)
                        if token_expires:
                            data["expires_ts"] = self._normalize_login_token_expires(
                                token_expires
                            )
                            data["expires_at"] = datetime.utcfromtimestamp(
                                data["expires_ts"]
                            ).isoformat() + "Z"
                        data["scan_seen"] = True
                        data["status"] = "scanned_wait_confirm"
                        self._log_qr_state(login_id, "scanned_wait_confirm", data)

                handler = client.add_handler(handlers.RawUpdateHandler(_raw_handler))
                session_data["handler"] = handler
            except Exception:
                pass

            session_data["expiry_task"] = asyncio.create_task(self._expire_qr_login(login_id, expires_ts))

            return {
                "login_id": login_id,
                "qr_uri": qr_uri,
                "expires_at": expires_at,
            }

        except FloodWait as e:
            try:
                await client.disconnect()
            except Exception:
                pass
            _release_account_lock()
            raise ValueError(f"请求过于频繁，请等待 {e.value} 秒后重试")
        except Exception as e:
            try:
                await client.disconnect()
            except Exception:
                pass
            _release_account_lock()
            raise ValueError(f"获取二维码失败: {str(e)}")

    async def get_qr_login_status(self, login_id: str) -> Dict[str, Any]:
        data = _qr_login_sessions.get(login_id)
        # A disconnected/slow HTTP poll can still be finishing its Telegram RPC.
        # Return the last known state instead of starting another import RPC.
        if data and data.get("polling"):
            return {"status": data.get("status", "waiting_scan"), "expires_at": data.get("expires_at")}
        if data:
            data["polling"] = True
        try:
            return await self._get_qr_login_status(login_id)
        finally:
            if data:
                data.pop("polling", None)

    async def _get_qr_login_status(self, login_id: str) -> Dict[str, Any]:
        from pyrogram import raw
        from pyrogram.errors import FloodWait, SessionPasswordNeeded, Unauthorized

        data = _qr_login_sessions.get(login_id)
        if not data:
            return {
                "status": "expired",
                "message": "二维码已过期或不存在",
            }

        if time.time() >= data.get("expires_ts", 0):
            self._log_qr_state(login_id, "expired", data)
            await self._cleanup_qr_login(login_id)
            return {
                "status": "expired",
                "message": "二维码已过期",
            }

        if data.get("status") == "password_required":
            self._log_qr_state(login_id, "password_required", data)
            return {
                "status": "password_required",
                "expires_at": data.get("expires_at"),
                "message": "需要 2FA 密码",
            }

        # 扫码后状态保持，避免回退到 waiting_scan
        if data.get("status") == "scanned_wait_confirm":
            data["scan_seen"] = True
            self._extend_qr_expires(data)

        # 未扫码时不要调用 ImportLoginToken，避免服务端轮转 token 导致二维码失效
        if not data.get("scan_seen") and data.get("status") == "waiting_scan":
            self._log_qr_state(login_id, "waiting_scan", data)
            return {
                "status": "waiting_scan",
                "expires_at": data.get("expires_at"),
            }

        client = data.get("client")
        token = data.get("token")
        migrate_dc_id = data.get("migrate_dc_id")

        async def _finalize_login(login_result: Any) -> Dict[str, Any]:
            # 标记授权用户
            user = await self._parse_login_user(client, login_result.authorization.user)
            await client.storage.user_id(user.id)
            await client.storage.is_bot(False)
            data["authorized"] = True
            data["authorized_user"] = user

            # 获取用户信息并持久化会话
            try:
                try:
                    me = await client.get_me()
                except Exception:
                    me = user

                try:
                    password_state = await client.get_password()
                except Exception:
                    password_state = None

                if password_state and getattr(password_state, "has_password", False):
                    data["status"] = "password_required"
                    data["scan_seen"] = True
                    self._extend_qr_expires(data)
                    self._log_qr_state(login_id, "password_required", data)
                    return {
                        "status": "password_required",
                        "expires_at": data.get("expires_at"),
                        "message": "需要 2FA 密码",
                    }

                await self._apply_migrate_auth(client, data)
                await self._persist_client_session(
                    client,
                    data.get("account_name"),
                    data.get("proxy"),
                    data.get("chat_cache_ttl_minutes"),
                )
            except SessionPasswordNeeded:
                data["status"] = "password_required"
                data["scan_seen"] = True
                self._extend_qr_expires(data)
                self._log_qr_state(login_id, "password_required", data)
                return {
                    "status": "password_required",
                    "expires_at": data.get("expires_at"),
                    "message": "需要 2FA 密码",
                }

            self._log_qr_state(login_id, "success", data)
            account_name = data.get("account_name")
            await self._cleanup_qr_login(login_id, preserve_session=True)

            account = None
            try:
                accounts = self.list_accounts(force_refresh=True)
                account = next(
                    (acc for acc in accounts if acc.get("name") == account_name),
                    None,
                )
            except Exception:
                account = None

            return {
                "status": "success",
                "message": "登录成功",
                "account": account,
                "user_id": me.id,
                "first_name": me.first_name,
                "username": me.username,
            }

        try:
            if not client.is_connected:
                await client.connect()

            result = None
            # 扫码确认后应再次调用 ExportLoginToken（官方流程）
            if data.get("status") == "scanned_wait_confirm":
                now = time.time()
                last_import_ts = data.get("last_import_ts", 0)
                if now - last_import_ts < 2:
                    status = (
                        "scanned_wait_confirm"
                        if data.get("scan_seen")
                        else data.get("status", "waiting_scan")
                    )
                    self._log_qr_state(login_id, status, data)
                    return {
                        "status": status,
                        "expires_at": data.get("expires_at"),
                    }
                data["last_import_ts"] = now

                token = data.get("token")
                migrate_dc_id = data.get("migrate_dc_id")
                result = None
                if token:
                    try:
                        for _ in range(2):
                            if migrate_dc_id:
                                # 登录尚未完成，目标 DC 通过 login token 授权。
                                session = await client.get_session(migrate_dc_id, export_authorization=False)
                                self._capture_migrate_auth(data, session)
                                result = await session.invoke(
                                    raw.functions.auth.ImportLoginToken(token=token)
                                )
                            else:
                                result = await client.invoke(
                                    raw.functions.auth.ImportLoginToken(token=token)
                                )

                            if isinstance(result, raw.types.auth.LoginTokenMigrateTo):
                                migrate_dc_id = result.dc_id
                                token = result.token
                                data["migrate_dc_id"] = migrate_dc_id
                                data["token"] = token
                                continue
                            break
                    except SessionPasswordNeeded:
                        data["status"] = "password_required"
                        data["scan_seen"] = True
                        data["authorized"] = True
                        self._extend_qr_expires(data)
                        self._log_qr_state(login_id, "password_required", data)
                        return {
                            "status": "password_required",
                            "expires_at": data.get("expires_at"),
                            "message": "需要 2FA 密码",
                        }
                    except Exception:
                        pass

                if isinstance(result, raw.types.auth.LoginTokenSuccess):
                    return await _finalize_login(result)
                if isinstance(result, raw.types.auth.LoginToken):
                    token_expires = getattr(result, "expires", None)
                    if token_expires:
                        data["expires_ts"] = self._normalize_login_token_expires(
                            token_expires
                        )
                        data["expires_at"] = datetime.utcfromtimestamp(
                            data["expires_ts"]
                        ).isoformat() + "Z"
                    if result.token:
                        data["token"] = result.token
                    data["status"] = "scanned_wait_confirm"

                # fallback: 再次调用 ExportLoginToken 获取最终状态（符合官方流程）
                if result is None or isinstance(result, raw.types.auth.LoginToken):
                    last_export_ts = data.get("last_export_ts", 0)
                    if now - last_export_ts >= 3:
                        api_id = data.get("api_id")
                        api_hash = data.get("api_hash")
                        if not api_id or not api_hash:
                            try:
                                from backend.services.config import get_config_service

                                tg_config = get_config_service().get_telegram_config()
                                api_id = os.getenv("TG_API_ID") or tg_config.get("api_id")
                                api_hash = os.getenv("TG_API_HASH") or tg_config.get("api_hash")
                                try:
                                    api_id = int(api_id) if api_id is not None else None
                                except (TypeError, ValueError):
                                    api_id = None
                                if isinstance(api_hash, str):
                                    api_hash = api_hash.strip()
                                if api_id and api_hash:
                                    data["api_id"] = api_id
                                    data["api_hash"] = api_hash
                            except Exception:
                                api_id = None
                                api_hash = None

                        if api_id and api_hash:
                            data["last_export_ts"] = now
                            try:
                                export_result = await client.invoke(
                                    raw.functions.auth.ExportLoginToken(
                                        api_id=api_id, api_hash=api_hash, except_ids=[]
                                    )
                                )
                                if isinstance(export_result, raw.types.auth.LoginTokenSuccess):
                                    return await _finalize_login(export_result)
                                if isinstance(export_result, raw.types.auth.LoginTokenMigrateTo):
                                    data["migrate_dc_id"] = export_result.dc_id
                                    data["token"] = export_result.token
                                    try:
                                        session = await client.get_session(export_result.dc_id, export_authorization=False)
                                        self._capture_migrate_auth(data, session)
                                        migrate_result = await session.invoke(
                                            raw.functions.auth.ImportLoginToken(token=export_result.token)
                                        )
                                        if isinstance(migrate_result, raw.types.auth.LoginTokenSuccess):
                                            return await _finalize_login(migrate_result)
                                    except SessionPasswordNeeded:
                                        data["status"] = "password_required"
                                        data["scan_seen"] = True
                                        self._extend_qr_expires(data)
                                        self._log_qr_state(login_id, "password_required", data)
                                        return {
                                            "status": "password_required",
                                            "expires_at": data.get("expires_at"),
                                            "message": "需要 2FA 密码",
                                        }
                                    except Exception:
                                        pass
                                elif isinstance(export_result, raw.types.auth.LoginToken):
                                    token_expires = getattr(export_result, "expires", None)
                                    if token_expires:
                                        data["expires_ts"] = self._normalize_login_token_expires(
                                            token_expires
                                        )
                                        data["expires_at"] = datetime.utcfromtimestamp(
                                            data["expires_ts"]
                                        ).isoformat() + "Z"
                                    if export_result.token:
                                        data["token"] = export_result.token
                                    data["status"] = "scanned_wait_confirm"
                            except Exception:
                                pass

            status = (
                "scanned_wait_confirm"
                if data.get("scan_seen")
                else data.get("status", "waiting_scan")
            )
            self._log_qr_state(login_id, status, data)
            return {
                "status": status,
                "expires_at": data.get("expires_at"),
            }

        except FloodWait as e:
            self._log_qr_state(login_id, "failed", data)
            await self._cleanup_qr_login(login_id)
            return {
                "status": "failed",
                "message": f"请求过于频繁，请等待 {e.value} 秒后重试",
            }
        except SessionPasswordNeeded:
            data = _qr_login_sessions.get(login_id)
            if data:
                data["status"] = "password_required"
                data["scan_seen"] = True
                self._extend_qr_expires(data)
                data["authorized"] = True
                self._log_qr_state(login_id, "password_required", data)
            return {
                "status": "password_required",
                "expires_at": data.get("expires_at") if data else None,
                "message": "需要 2FA 密码",
            }
        except Unauthorized:
            self._log_qr_state(login_id, "failed", data)
            await self._cleanup_qr_login(login_id)
            return {
                "status": "failed",
                "message": "登录失败，请重试",
            }
        except Exception:
            self._log_qr_state(login_id, "failed", data)
            await self._cleanup_qr_login(login_id)
            return {
                "status": "failed",
                "message": "登录失败，请重试",
            }

    async def submit_qr_password(self, login_id: str, password: str) -> Dict[str, Any]:
        from pyrogram import raw
        from pyrogram.errors import (
            FloodWait,
            PasswordHashInvalid,
            SessionPasswordNeeded,
            Unauthorized,
        )
        from pyrogram.utils import compute_password_check

        password = (password or "").strip()
        if not password:
            raise ValueError("2FA 密码不能为空")

        data = _qr_login_sessions.get(login_id)
        if not data:
            raise ValueError("二维码已过期或不存在")

        if time.time() >= data.get("expires_ts", 0):
            if data.get("status") in {"password_required", "authorized"}:
                self._extend_qr_expires(data)
            else:
                await self._cleanup_qr_login(login_id)
                raise ValueError("二维码已过期")

        client = data.get("client")
        if not client:
            await self._cleanup_qr_login(login_id)
            raise ValueError("登录会话已失效")

        account_lock = data.get("lock")
        if account_lock and not account_lock.locked():
            await account_lock.acquire()

        global_semaphore = get_global_semaphore()

        async def _finalize_password_login(user_fallback=None) -> Dict[str, Any]:
            user_from_password = None
            try:
                if data.get("migrate_dc_id"):
                    session = await client.get_session(data.get("migrate_dc_id"), export_authorization=False)
                    self._capture_migrate_auth(data, session)
                    auth = await session.invoke(
                        raw.functions.auth.CheckPassword(
                            password=compute_password_check(
                                await session.invoke(raw.functions.account.GetPassword()),
                                password,
                            )
                        )
                    )
                    user_from_password = await self._parse_login_user(client, auth.user)
                    await client.storage.user_id(user_from_password.id)
                    await client.storage.is_bot(False)
                    data["authorized"] = True
                    data["authorized_user"] = user_from_password
                else:
                    user_from_password = await client.check_password(password)
                    data["authorized"] = True
                    data["authorized_user"] = user_from_password
            except PasswordHashInvalid:
                await self._cleanup_qr_login(login_id)
                raise ValueError("两步验证密码错误")

            try:
                if user_from_password is not None:
                    me = user_from_password
                else:
                    me = await client.get_me()
            except Exception:
                me = user_fallback

            await self._apply_migrate_auth(client, data)
            await self._persist_client_session(
                client, data.get("account_name"), data.get("proxy")
            )

            account_name = data.get("account_name")
            self._log_qr_state(login_id, "success", data)
            await self._cleanup_qr_login(login_id, preserve_session=True)

            account = None
            try:
                accounts = self.list_accounts(force_refresh=True)
                account = next(
                    (acc for acc in accounts if acc.get("name") == account_name),
                    None,
                )
            except Exception:
                account = None

            return {
                "status": "success",
                "message": "登录成功",
                "account": account,
                "user_id": getattr(me, "id", None),
                "first_name": getattr(me, "first_name", None),
                "username": getattr(me, "username", None),
            }

        try:
            async with global_semaphore:
                if not client.is_connected:
                    await client.connect()

                async def _ensure_authorized():
                    if data.get("authorized"):
                        return data.get("authorized_user")

                    token = data.get("token")
                    migrate_dc_id = data.get("migrate_dc_id")
                    result = None
                    if token:
                        try:
                            for _ in range(2):
                                if migrate_dc_id:
                                    session = await client.get_session(migrate_dc_id, export_authorization=False)
                                    self._capture_migrate_auth(data, session)
                                    result = await session.invoke(
                                        raw.functions.auth.ImportLoginToken(token=token)
                                    )
                                else:
                                    result = await client.invoke(
                                        raw.functions.auth.ImportLoginToken(token=token)
                                    )

                                if isinstance(result, raw.types.auth.LoginTokenMigrateTo):
                                    migrate_dc_id = result.dc_id
                                    token = result.token
                                    data["migrate_dc_id"] = migrate_dc_id
                                    data["token"] = token
                                    continue
                                break
                        except SessionPasswordNeeded:
                            data["status"] = "password_required"
                            data["scan_seen"] = True
                            data["authorized"] = True
                            self._extend_qr_expires(data)
                            return data.get("authorized_user")
                        except Exception:
                            result = None

                    if isinstance(result, raw.types.auth.LoginTokenSuccess):
                        user = await self._parse_login_user(client, result.authorization.user)
                        await client.storage.user_id(user.id)
                        await client.storage.is_bot(False)
                        data["authorized"] = True
                        data["authorized_user"] = user
                        return user
                    if isinstance(result, raw.types.auth.LoginToken):
                        token_expires = getattr(result, "expires", None)
                        if token_expires:
                            data["expires_ts"] = self._normalize_login_token_expires(
                                token_expires
                            )
                            data["expires_at"] = datetime.utcfromtimestamp(
                                data["expires_ts"]
                            ).isoformat() + "Z"
                        if result.token:
                            data["token"] = result.token

                    api_id = data.get("api_id")
                    api_hash = data.get("api_hash")
                    if not api_id or not api_hash:
                        try:
                            from backend.services.config import get_config_service

                            tg_config = get_config_service().get_telegram_config()
                            api_id = os.getenv("TG_API_ID") or tg_config.get("api_id")
                            api_hash = os.getenv("TG_API_HASH") or tg_config.get(
                                "api_hash"
                            )
                            try:
                                api_id = int(api_id) if api_id is not None else None
                            except (TypeError, ValueError):
                                api_id = None
                            if isinstance(api_hash, str):
                                api_hash = api_hash.strip()
                            if api_id and api_hash:
                                data["api_id"] = api_id
                                data["api_hash"] = api_hash
                        except Exception:
                            api_id = None
                            api_hash = None

                    if api_id and api_hash:
                        try:
                            export_result = await client.invoke(
                                raw.functions.auth.ExportLoginToken(
                                    api_id=api_id, api_hash=api_hash, except_ids=[]
                                )
                            )
                            if isinstance(
                                export_result, raw.types.auth.LoginTokenSuccess
                            ):
                                user = await self._parse_login_user(
                                    client, export_result.authorization.user
                                )
                                await client.storage.user_id(user.id)
                                await client.storage.is_bot(False)
                                data["authorized"] = True
                                data["authorized_user"] = user
                                return user
                            if isinstance(
                                export_result, raw.types.auth.LoginTokenMigrateTo
                            ):
                                data["migrate_dc_id"] = export_result.dc_id
                                data["token"] = export_result.token
                                try:
                                    session = await client.get_session(export_result.dc_id, export_authorization=False)
                                    self._capture_migrate_auth(data, session)
                                    migrate_result = await session.invoke(
                                        raw.functions.auth.ImportLoginToken(
                                            token=export_result.token
                                        )
                                    )
                                    if isinstance(
                                        migrate_result,
                                        raw.types.auth.LoginTokenSuccess,
                                    ):
                                        user = await self._parse_login_user(
                                            client, migrate_result.authorization.user
                                        )
                                        await client.storage.user_id(user.id)
                                        await client.storage.is_bot(False)
                                        data["authorized"] = True
                                        data["authorized_user"] = user
                                        return user
                                except SessionPasswordNeeded:
                                    data["status"] = "password_required"
                                    data["scan_seen"] = True
                                    data["authorized"] = True
                                    self._extend_qr_expires(data)
                                    return data.get("authorized_user")
                                except Exception:
                                    pass
                            elif isinstance(export_result, raw.types.auth.LoginToken):
                                token_expires = getattr(export_result, "expires", None)
                                if token_expires:
                                    data["expires_ts"] = (
                                        self._normalize_login_token_expires(token_expires)
                                    )
                                    data["expires_at"] = datetime.utcfromtimestamp(
                                        data["expires_ts"]
                                    ).isoformat() + "Z"
                                if export_result.token:
                                    data["token"] = export_result.token
                        except Exception:
                            pass

                    return data.get("authorized_user")

                if data.get("status") == "password_required" or data.get("authorized"):
                    try:
                        return await _finalize_password_login(
                            data.get("authorized_user")
                        )
                    except Unauthorized:
                        user = await _ensure_authorized()
                        if not data.get("authorized"):
                            self._extend_qr_expires(data)
                            raise ValueError("请先在手机端确认登录")
                        return await _finalize_password_login(user)

                token = data.get("token")
                migrate_dc_id = data.get("migrate_dc_id")
                result = None
                try:
                    for _ in range(2):
                        if migrate_dc_id:
                            session = await client.get_session(migrate_dc_id, export_authorization=False)
                            self._capture_migrate_auth(data, session)
                            result = await session.invoke(
                                raw.functions.auth.ImportLoginToken(token=token)
                            )
                        else:
                            result = await client.invoke(
                                raw.functions.auth.ImportLoginToken(token=token)
                            )

                        if isinstance(result, raw.types.auth.LoginTokenMigrateTo):
                            migrate_dc_id = result.dc_id
                            token = result.token
                            data["migrate_dc_id"] = migrate_dc_id
                            data["token"] = token
                            continue
                        break
                except SessionPasswordNeeded:
                    data["status"] = "password_required"
                    data["scan_seen"] = True
                    data["authorized"] = True
                    self._extend_qr_expires(data)
                    return await _finalize_password_login()

                if isinstance(result, raw.types.auth.LoginToken):
                    token_expires = getattr(result, "expires", None)
                    if token_expires:
                        data["expires_ts"] = self._normalize_login_token_expires(
                            token_expires
                        )
                        data["expires_at"] = datetime.utcfromtimestamp(
                            data["expires_ts"]
                        ).isoformat() + "Z"
                    if data.get("token") != result.token:
                        data["token"] = result.token
                    raise ValueError("请先在手机端确认登录")

                if isinstance(result, raw.types.auth.LoginTokenSuccess):
                    user = await self._parse_login_user(client, result.authorization.user)
                    await client.storage.user_id(user.id)
                    await client.storage.is_bot(False)
                    data["authorized"] = True
                    data["authorized_user"] = user

                    try:
                        try:
                            me = await client.get_me()
                        except Exception:
                            me = user

                        try:
                            password_state = await client.get_password()
                        except Exception:
                            password_state = None

                        if password_state and getattr(password_state, "has_password", False):
                            return await _finalize_password_login(user)

                        await self._apply_migrate_auth(client, data)
                        await self._persist_client_session(
                            client, data.get("account_name"), data.get("proxy")
                        )
                    except SessionPasswordNeeded:
                        data["status"] = "password_required"
                        data["scan_seen"] = True
                        return await _finalize_password_login(user)

                    try:
                        await client.disconnect()
                    except Exception:
                        pass

                    account_name = data.get("account_name")
                    await self._cleanup_qr_login(login_id, preserve_session=True)

                    account = None
                    try:
                        accounts = self.list_accounts(force_refresh=True)
                        account = next(
                            (acc for acc in accounts if acc.get("name") == account_name),
                            None,
                        )
                    except Exception:
                        account = None

                    return {
                        "status": "success",
                        "message": "登录成功",
                        "account": account,
                        "user_id": getattr(me, "id", None),
                        "first_name": getattr(me, "first_name", None),
                        "username": getattr(me, "username", None),
                    }

                raise ValueError("请先在手机端确认登录")

        except FloodWait as e:
            await self._cleanup_qr_login(login_id)
            raise ValueError(f"请求过于频繁，请等待 {e.value} 秒后重试")
        except Unauthorized:
            if data and data.get("status") in {"password_required", "scanned_wait_confirm"}:
                self._extend_qr_expires(data)
                raise ValueError("请先在手机端确认登录")
            await self._cleanup_qr_login(login_id)
            raise ValueError("登录失败，请重试")
        except ValueError:
            raise
        except Exception:
            if data and data.get("status") in {"password_required", "scanned_wait_confirm"}:
                self._extend_qr_expires(data)
                raise ValueError("登录失败，请重试")
            await self._cleanup_qr_login(login_id)
            raise ValueError("登录失败，请重试")

    async def cancel_qr_login(self, login_id: str) -> bool:
        data = _qr_login_sessions.get(login_id)
        if not data:
            return False
        self._log_qr_state(login_id, "cancelled", data)
        await self._cleanup_qr_login(login_id)
        return True

    def login_sync(
        self,
        account_name: str,
        phone_number: str,
        phone_code: Optional[str] = None,
        phone_code_hash: Optional[str] = None,
        password: Optional[str] = None,
        proxy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        同步版本的登录方法（用于 FastAPI）

        如果只提供 phone_number，则发送验证码
        如果提供了 phone_code，则验证登录
        """

        try:
            if phone_code is None:
                # 发送验证码
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result = loop.run_until_complete(
                        self.start_login(account_name, phone_number, proxy)
                    )
                finally:
                    loop.close()
            else:
                # 验证登录
                if not phone_code_hash:
                    raise ValueError("缺少 phone_code_hash")

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    result = loop.run_until_complete(
                        self.verify_login(
                            account_name,
                            phone_number,
                            phone_code,
                            phone_code_hash,
                            password,
                            proxy,
                        )
                    )
                finally:
                    loop.close()

            return result
        except Exception as e:
            # 重新抛出异常，保留原始错误信息
            raise e


# 创建全局实例
_telegram_service: Optional[TelegramService] = None


def get_telegram_service() -> TelegramService:
    global _telegram_service
    if _telegram_service is None:
        _telegram_service = TelegramService()
    return _telegram_service
