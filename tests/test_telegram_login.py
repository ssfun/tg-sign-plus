import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pyrogram import Client, raw, types
from pyrogram.errors import PhoneCodeInvalid, SessionPasswordNeeded, Unauthorized

from backend.services import sign_tasks, telegram
from backend.utils import tg_session


@pytest.fixture
def login_env(monkeypatch):
    service = telegram.TelegramService()
    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(1)
    saved = {}
    profiles = {}

    async def refresh_chats(account_name):
        # The real cache loader takes both resources held by phone login.
        async with lock:
            async with semaphore:
                return []

    cache = SimpleNamespace(
        ensure_account_chat_cache_meta=Mock(),
        refresh_account_chats=AsyncMock(side_effect=refresh_chats),
    )
    monkeypatch.setattr(sign_tasks, "get_sign_task_service", lambda: cache)
    monkeypatch.setattr(telegram, "get_global_semaphore", lambda: semaphore)
    monkeypatch.setattr(telegram, "_login_sessions", {})
    monkeypatch.setattr(telegram, "_qr_login_sessions", {})
    monkeypatch.setattr(
        telegram,
        "set_account_session_string",
        lambda name, value: saved.update({name: value}),
    )
    monkeypatch.setattr(
        telegram, "delete_account_session_string", lambda name: saved.pop(name, None)
    )
    monkeypatch.setattr(
        tg_session,
        "set_account_profile",
        lambda name, **kw: profiles.update({name: kw}),
    )
    monkeypatch.setattr(
        service, "list_accounts", lambda **kw: [{"name": name} for name in saved]
    )
    user = types.User(id=123, first_name="Test", username="test")
    client = SimpleNamespace(
        is_connected=True,
        is_initialized=False,
        sign_in=AsyncMock(return_value=user),
        check_password=AsyncMock(return_value=user),
        get_me=AsyncMock(return_value=user),
        get_password=AsyncMock(return_value=SimpleNamespace(has_password=False)),
        export_session_string=AsyncMock(return_value="test-session"),
        disconnect=AsyncMock(),
        invoke=AsyncMock(),
        get_session=AsyncMock(spec=Client.get_session),
        storage=SimpleNamespace(
            user_id=AsyncMock(),
            is_bot=AsyncMock(),
            dc_id=AsyncMock(),
            auth_key=AsyncMock(),
        ),
    )
    return SimpleNamespace(
        service=service,
        lock=lock,
        semaphore=semaphore,
        saved=saved,
        profiles=profiles,
        cache=cache,
        client=client,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("password", [None, "test-password"])
async def test_phone_login_returns_without_waiting_for_chat_refresh(
    login_env, password
):
    env = login_env
    await env.lock.acquire()
    telegram._login_sessions["account_+100"] = {
        "client": env.client,
        "lock": env.lock,
        "proxy": "socks5://localhost:1080",
        "chat_cache_ttl_minutes": 90,
    }
    if password:
        env.client.sign_in.side_effect = SessionPasswordNeeded
    result = await asyncio.wait_for(
        env.service.verify_login("account", "+100", "12-3 45", "hash", password), 1
    )
    assert result["success"] is True
    assert env.saved == {"account": "test-session"}
    assert env.profiles["account"]["proxy"] == "socks5://localhost:1080"
    assert not env.lock.locked()
    assert not env.semaphore.locked()
    assert not telegram._login_sessions
    env.client.sign_in.assert_awaited_once_with("+100", "hash", "12345")
    env.client.disconnect.assert_awaited_once()
    env.cache.refresh_account_chats.assert_not_awaited()
    if password:
        env.client.check_password.assert_awaited_once_with(password)


@pytest.mark.asyncio
async def test_phone_invalid_code_cleans_up_without_persisting(login_env):
    env = login_env
    await env.lock.acquire()
    telegram._login_sessions["account_+100"] = {"client": env.client, "lock": env.lock}
    env.client.sign_in.side_effect = PhoneCodeInvalid
    with pytest.raises(ValueError, match="验证码错误"):
        await env.service.verify_login("account", "+100", "12345", "hash")
    assert not env.saved
    assert not env.lock.locked()
    assert not telegram._login_sessions


def qr_success():
    return raw.types.auth.LoginTokenSuccess(
        authorization=raw.types.auth.Authorization(
            user=raw.types.User(
                id=123, first_name="Test", usernames=[], restriction_reason=[]
            )
        )
    )


async def prepare_qr(env, status):
    await env.lock.acquire()
    telegram._qr_login_sessions["login"] = {
        "client": env.client,
        "lock": env.lock,
        "account_name": "account",
        "status": status,
        "scan_seen": status != "waiting_scan",
        "token": b"token",
        "expires_ts": time.time() + 300,
        "api_id": 123,
        "api_hash": "test-hash",
    }


@pytest.mark.asyncio
async def test_qr_waiting_scan_and_expired_status_work_with_installed_kurigram(
    login_env,
):
    env = login_env
    assert (await env.service.get_qr_login_status("missing"))["status"] == "expired"
    await prepare_qr(env, "waiting_scan")
    assert (await env.service.get_qr_login_status("login"))["status"] == "waiting_scan"
    env.client.invoke.assert_not_awaited()
    env.lock.release()


@pytest.mark.asyncio
@pytest.mark.parametrize("migration", ["none", "import", "export"])
async def test_qr_login_persists_and_releases_lock(login_env, migration):
    env = login_env
    await prepare_qr(env, "scanned_wait_confirm")
    migrated = SimpleNamespace(
        dc_id=2, auth_key=b"dc-key", invoke=AsyncMock(return_value=qr_success())
    )
    env.client.get_session.return_value = migrated
    if migration == "none":
        env.client.invoke.return_value = qr_success()
    elif migration == "import":
        env.client.invoke.return_value = raw.types.auth.LoginTokenMigrateTo(
            dc_id=2, token=b"migrated-token"
        )
    else:
        env.client.invoke.side_effect = [
            raw.types.auth.LoginToken(
                expires=int(time.time()) + 300, token=b"new-token"
            ),
            raw.types.auth.LoginTokenMigrateTo(dc_id=2, token=b"migrated-token"),
        ]
    result = await asyncio.wait_for(env.service.get_qr_login_status("login"), 1)
    assert result["status"] == "success"
    assert env.saved == {"account": "test-session"}
    assert not env.lock.locked()
    assert not telegram._qr_login_sessions
    env.client.disconnect.assert_awaited_once()
    env.cache.refresh_account_chats.assert_not_awaited()
    if migration != "none":
        env.client.get_session.assert_awaited_once_with(2, export_authorization=False)
        env.client.storage.dc_id.assert_awaited_once_with(2)
        env.client.storage.auth_key.assert_awaited_once_with(b"dc-key")


@pytest.mark.asyncio
@pytest.mark.parametrize("migrated", [False, True])
@pytest.mark.parametrize("status", ["password_required", "scanned_wait_confirm"])
async def test_qr_password_login_persists_without_chat_refresh(
    login_env, monkeypatch, migrated, status
):
    env = login_env
    await prepare_qr(env, status)
    env.client.invoke.return_value = qr_success()
    env.client.get_password.return_value = SimpleNamespace(has_password=True)
    if migrated:
        telegram._qr_login_sessions["login"]["migrate_dc_id"] = 2
        responses = [object(), qr_success().authorization]
        if status == "scanned_wait_confirm":
            responses.insert(0, qr_success())
        session = SimpleNamespace(
            dc_id=2, auth_key=b"dc-key", invoke=AsyncMock(side_effect=responses)
        )
        env.client.get_session.return_value = session
        monkeypatch.setattr(
            "pyrogram.utils.compute_password_check", lambda *args: "password-check"
        )
    result = await asyncio.wait_for(
        env.service.submit_qr_password("login", "test-password"), 1
    )
    assert result["status"] == "success"
    assert env.saved == {"account": "test-session"}
    assert not env.lock.locked()
    assert not env.semaphore.locked()
    assert not telegram._qr_login_sessions
    env.cache.refresh_account_chats.assert_not_awaited()
    if migrated:
        assert env.client.get_session.await_count == (
            2 if status == "scanned_wait_confirm" else 1
        )
        for args in env.client.get_session.await_args_list:
            assert args.args == (2,)
            assert args.kwargs == {"export_authorization": False}
    else:
        env.client.check_password.assert_awaited_once_with("test-password")


@pytest.mark.asyncio
@pytest.mark.parametrize("recovery", ["import", "export", "export_migrate"])
async def test_qr_password_authorization_recovery(login_env, monkeypatch, recovery):
    env = login_env
    await prepare_qr(env, "password_required")
    env.client.check_password.side_effect = [
        Unauthorized(),
        env.client.get_me.return_value,
    ]
    pending = raw.types.auth.LoginToken(
        expires=int(time.time()) + 300, token=b"new-token"
    )
    migration = raw.types.auth.LoginTokenMigrateTo(dc_id=2, token=b"migrated-token")
    session = SimpleNamespace(
        dc_id=2,
        auth_key=b"dc-key",
        invoke=AsyncMock(
            side_effect=[
                qr_success(),
                object(),
                qr_success().authorization,
            ]
        ),
    )
    env.client.get_session.return_value = session
    monkeypatch.setattr(
        "pyrogram.utils.compute_password_check", lambda *args: "password-check"
    )
    if recovery == "import":
        telegram._qr_login_sessions["login"]["migrate_dc_id"] = 2
        session.invoke.side_effect = [
            Unauthorized(),
            qr_success(),
            object(),
            qr_success().authorization,
        ]
    else:
        env.client.invoke.side_effect = [
            pending,
            migration if recovery == "export_migrate" else qr_success(),
        ]
    result = await asyncio.wait_for(
        env.service.submit_qr_password("login", "test-password"), 1
    )
    assert result["status"] == "success"
    assert env.saved == {"account": "test-session"}
    assert not env.lock.locked()
    assert not env.semaphore.locked()
    assert not telegram._qr_login_sessions
    if recovery != "export":
        for args in env.client.get_session.await_args_list:
            assert args.args == (2,)
            assert args.kwargs == {"export_authorization": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "cancel", "expire"])
@pytest.mark.parametrize("initialized", [False, True])
async def test_qr_cleanup_closes_dc_sessions_with_real_client_lifecycle(
    login_env, outcome, initialized
):
    env = login_env
    # Keep the real stop/terminate/disconnect methods; replace only I/O resources.
    client = Client("cleanup-test", api_id=123, api_hash="test", in_memory=True)
    primary = SimpleNamespace(stop=AsyncMock())
    migrated = SimpleNamespace(stop=AsyncMock())
    client.session = primary
    client.sessions[2] = migrated
    client.storage = SimpleNamespace(save=AsyncMock(), close=AsyncMock())
    client.dispatcher = SimpleNamespace(stop=AsyncMock())
    client.updates_watchdog_task = None
    client.is_connected = True
    client.is_initialized = initialized
    env.client = client
    await prepare_qr(env, "scanned_wait_confirm")
    env.saved["account"] = "test-session"

    if outcome == "success":
        await env.service._cleanup_qr_login("login", preserve_session=True)
    elif outcome == "cancel":
        assert await env.service.cancel_qr_login("login") is True
    else:
        telegram._qr_login_sessions["login"]["expires_ts"] = 0
        await env.service._expire_qr_login("login", 0)

    migrated.stop.assert_awaited_once()
    primary.stop.assert_awaited_once()
    client.storage.close.assert_awaited_once()
    assert not client.sessions
    assert not client.is_connected
    assert not env.lock.locked()
    assert not telegram._qr_login_sessions
    assert ("account" in env.saved) == (outcome == "success")
    # Cleanup can safely be repeated by a later timer or cancellation request.
    await env.service._cleanup_qr_login("login", preserve_session=True)
    migrated.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_qr_cleanup_continues_after_one_dc_stop_fails(login_env):
    env = login_env
    failed = SimpleNamespace(stop=AsyncMock(side_effect=ConnectionError("closed")))
    other = SimpleNamespace(stop=AsyncMock())
    env.client.sessions = {2: failed, 3: other}
    await prepare_qr(env, "scanned_wait_confirm")
    await env.service.cancel_qr_login("login")
    failed.stop.assert_awaited_once()
    other.stop.assert_awaited_once()
    env.client.disconnect.assert_awaited_once()
    assert not env.client.sessions
    assert not env.lock.locked()
    assert not telegram._qr_login_sessions
