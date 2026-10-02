"""Review regression acceptance: real HTTP routes and real Kurigram teardown.

Invoked by resource_efficiency.py in its isolated application. Only external
Telegram transport is synthetic. Failure scenarios precede the implementation
in resource_efficiency_scenarios.txt.
"""

from __future__ import annotations

import asyncio
import os
import time
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from pyrogram import Client as NativeClient
from pyrogram.session import Session
from pyrogram.session.session import SessionState


async def run_lifecycle_acceptance(app, headers, cookies):
    from backend.services import telegram
    from backend.utils.account_locks import get_account_lock
    from backend.utils.tg_session import get_account_profile, set_account_profile

    created = []

    class Transport:
        def __init__(self, *args, **kwargs):
            self.proxy = kwargs.get("proxy")
            self.is_connected = False
            self.is_initialized = False
            self.sessions = {}
            self.session = None
            self.disconnect_started = asyncio.Event()
            self.disconnect_completed = False
            created.append(self)

        async def connect(self):
            self.is_connected = True

        async def get_me(self):
            return SimpleNamespace(id=123)

        async def disconnect(self):
            self.disconnect_started.set()
            self.is_connected = False
            self.disconnect_completed = True

    class DeadlineTransport(Transport):
        async def send_code(self, phone):
            await asyncio.sleep(0.8)
            raise RuntimeError("synthetic send failure just before deadline")

        async def disconnect(self):
            self.disconnect_started.set()
            await asyncio.sleep(0.5)
            self.is_connected = False
            self.disconnect_completed = True

    class CancelTransport(DeadlineTransport):
        async def send_code(self, phone):
            raise RuntimeError("synthetic immediate send failure")

    receipts = {}
    request_headers = {**headers, "X-CSRF-Token": cookies["tg-signer-csrf"]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=request_headers,
        cookies=cookies,
    ) as http:
        old_proxy = get_account_profile("alpha").get("proxy") or ""
        try:
            for name, env_proxy, account_proxy, expected_port in (
                ("direct", "", "", None),
                ("environment", "socks5://127.0.0.1:10999", "", 10999),
                (
                    "account_override",
                    "socks5://127.0.0.1:10999",
                    "socks5://127.0.0.1:11000",
                    11000,
                ),
            ):
                set_account_profile("alpha", proxy=account_proxy)
                with (
                    patch.dict(os.environ, {"TG_PROXY": env_proxy}),
                    patch("pyrogram.Client", Transport),
                ):
                    response = await http.post(
                        "/api/accounts/status/check", json={"account_names": ["alpha"]}
                    )
                assert response.status_code == 200, response.text
                assert response.json()["results"][0]["code"] == "OK", response.text
                client = created[-1]
                actual_port = client.proxy["port"] if client.proxy else None
                assert actual_port == expected_port, (name, client.proxy)
                assert not client.is_connected
                receipts[name] = {"proxy_port": actual_port, "closed": True}
        finally:
            set_account_profile("alpha", proxy=old_proxy)

        with (
            patch.dict(os.environ, {"TG_LOGIN_TIMEOUT": "1"}),
            patch("pyrogram.Client", DeadlineTransport),
        ):
            start = time.monotonic()
            response = await http.post(
                "/api/accounts/login/start",
                json={"account_name": "cleanup-deadline", "phone_number": "+100"},
            )
            elapsed = time.monotonic() - start
        assert response.status_code == 400, response.text
        assert created[-1].disconnect_completed and not created[-1].is_connected
        assert not get_account_lock("cleanup-deadline").locked()
        assert not any(
            s.get("account_name") == "cleanup-deadline"
            for s in telegram._login_sessions.values()
        )
        receipts["deadline_during_cleanup"] = {
            "closed": True,
            "elapsed_ms": round(elapsed * 1000, 2),
        }

        with patch("pyrogram.Client", CancelTransport):
            request = asyncio.create_task(
                http.post(
                    "/api/accounts/login/start",
                    json={"account_name": "cleanup-cancel", "phone_number": "+100"},
                )
            )
            while not created or not isinstance(created[-1], CancelTransport):
                await asyncio.sleep(0)
            client = created[-1]
            await asyncio.wait_for(client.disconnect_started.wait(), timeout=2)
            request.cancel()
            await asyncio.sleep(0.02)
            request.cancel()
            try:
                await request
                raise AssertionError("request cancellation was swallowed")
            except asyncio.CancelledError:
                pass
        # ASGI may finish cancelling the HTTP task before Python 3.10 wait_for's
        # child coroutine has finished its protected cleanup.
        lock = get_account_lock("cleanup-cancel")
        await asyncio.wait_for(lock.acquire(), timeout=2)
        lock.release()
        assert client.disconnect_completed and not client.is_connected
        receipts["repeated_cancellation"] = {
            "closed": True,
            "cancellation_propagated": True,
        }

    class Socket:
        def __init__(self):
            self.closed = asyncio.Event()

        async def close(self):
            self.closed.set()

    class Storage:
        closed = False

        async def close(self):
            self.closed = True

    for target in ("primary", "migrated"):
        client = NativeClient(
            "synthetic",
            api_id=1234,
            api_hash="synthetic",
            in_memory=True,
            no_updates=True,
        )
        client.is_connected = True
        client.storage = Storage()
        sessions = []
        for dc in range(2, 4 if target == "migrated" else 3):
            session = Session(client, dc, "127.0.0.1", 443, b"0" * 256, False)
            session._state = SessionState.STARTED
            session.connection = Socket()
            sessions.append(session)
        client.session = sessions[0]
        if target == "migrated":
            client.sessions[3] = sessions[1]
        slow = sessions[-1]
        slow.ping_task = asyncio.create_task(asyncio.sleep(30))
        slow.recv_task = asyncio.create_task(slow.connection.closed.wait())
        packet = asyncio.create_task(asyncio.sleep(30))
        slow.pending_tasks.add(packet)
        packet.add_done_callback(slow.pending_tasks.discard)
        owned_tasks = [slow.ping_task, slow.recv_task, packet]
        try:
            await asyncio.wait_for(
                telegram.TelegramService._close_temporary_client(client), timeout=15
            )
            assert all(s.connection.closed.is_set() for s in sessions), target
            assert client.storage.closed and not client.is_connected, target
            assert not client.sessions
            assert all(task.done() for task in owned_tasks), target
            receipts[f"kurigram_{target}_timeout"] = {
                "socket_closed": True,
                "storage_closed": True,
                "tasks_drained": True,
            }
        finally:
            # Keep a failing acceptance run isolated too.
            for session in sessions:
                await session.connection.close()
            for task in owned_tasks:
                task.cancel()
            await asyncio.gather(*owned_tasks, return_exceptions=True)
    return receipts
