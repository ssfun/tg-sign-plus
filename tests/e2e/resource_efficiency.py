"""Repeatable HTTP + SQLite acceptance, with Telegram replaced only at transport.
Run: python tests/e2e/resource_efficiency.py --output /tmp/tg-resource-e2e
Use --serve PORT for browser verification against the same isolated application.
Requires the project's runtime dependencies. Never touches configured real data.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--serve", type=int)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
data = tempfile.TemporaryDirectory(prefix="tg-efficiency-e2e-")
os.environ.update(
    APP_DATA_DIR=data.name,
    APP_DATABASE_URL=f"sqlite:///{data.name}/test.sqlite",
    APP_SECRET_KEY="isolated-efficiency-e2e-secret",
    TG_API_ID="1234",
    TG_API_HASH="synthetic",
    TG_PHONE_LOGIN_TTL="300" if args.serve else "1",
    APP_ADMIN_PASSWORD="Efficiency123!",
    PYTHONDONTWRITEBYTECODE="1",
)

from fastapi.testclient import TestClient
from sqlalchemy import event, text
import backend.models
from backend.main import app
from backend.core.database import get_engine, get_session_local, init_engine
from backend.core.schema_migrator import upgrade_schema
from backend.core.auth import create_access_token
from backend.core.security import hash_password
from backend.models.user import User
from backend.models.sign_task_run import SignTaskRun
from backend.models.refresh_token import RefreshToken
from backend.models.audit_log import AuditLog
from backend.repositories.sign_task_config_repo import get_sign_task_config_repo
from backend.repositories.sign_task_history_repo import get_sign_task_history_repo
from backend.services.sign_tasks import get_sign_task_service
from backend.services.config import get_config_service
from backend.services import telegram
from backend.utils.account_locks import get_account_lock
from backend.utils.tg_session import set_account_session_string
import backend.scheduler as scheduler
from pyrogram.errors import SessionPasswordNeeded, PasswordHashInvalid
from tg_signer.event_runner import SignEventRunner
from tg_signer.core import UserSigner

transport = {
    "clients": [],
    "connect_delay": 0.0,
    "verify_delay": 0.0,
    "needs_password": False,
    "qr_delay": 0.0,
    "qr_active": 0,
    "qr_max_active": 0,
}


class FakeTelegram:
    def __init__(self, *a, **kw):
        self.is_connected = False
        self.is_initialized = False
        self.disconnects = 0
        self.sessions = {}
        self.session = None
        transport["clients"].append(self)

    async def connect(self):
        self.is_connected = True
        await asyncio.sleep(transport["connect_delay"])

    async def disconnect(self):
        self.disconnects += 1
        self.is_connected = False

    async def get_me(self):
        return SimpleNamespace(id=123, first_name="Synthetic", username="synthetic")

    async def send_code(self, phone):
        return SimpleNamespace(phone_code_hash=f"hash-{len(transport['clients'])}")

    async def sign_in(self, *a):
        await asyncio.sleep(transport["verify_delay"])
        if transport["needs_password"]:
            raise SessionPasswordNeeded()

    async def check_password(self, password):
        if password != "correct":
            raise PasswordHashInvalid()

    async def export_session_string(self):
        return "synthetic-session"

    async def initialize(self):
        self.is_initialized = True

    async def stop(self):
        self.is_initialized = False
        await self.disconnect()

    def add_handler(self, handler):
        return (handler, 0)

    def remove_handler(self, *a):
        pass

    async def invoke(self, query):
        from pyrogram import raw

        transport["qr_active"] += 1
        transport["qr_max_active"] = max(
            transport["qr_max_active"], transport["qr_active"]
        )
        try:
            await asyncio.sleep(transport["qr_delay"])
            return raw.types.auth.LoginToken(
                expires=int(time.time()) + 60, token=b"synthetic-token"
            )
        finally:
            transport["qr_active"] -= 1


init_engine()
engine = get_engine()
upgrade_schema(engine)
with get_session_local()() as db:
    db.add(User(username="efficiency", password_hash=hash_password("Efficiency123!")))
    db.commit()
config_repo = get_sign_task_config_repo()
history_repo = get_sign_task_history_repo()
service = get_sign_task_service()
now = datetime.utcnow()
flow_items = [
    {
        "ts": now.isoformat(),
        "event": "log",
        "stage": "message",
        "level": "info",
        "text": f"synthetic event {i}",
        "meta": {},
        "text_visible": True,
    }
    for i in range(200)
]
for a in ("alpha", "beta"):
    set_account_session_string(a, "synthetic-session")
    for n in range(10):
        config_repo.save_config(
            f"task-{n}",
            a,
            {
                "sign_at": "09:00",
                "enabled": False,
                "engine": "event",
                "chats": [
                    {"chat_id": 123, "actions": [{"action": 1, "text": "/sign"}]}
                ],
            },
        )
        for i in range(35):
            service._save_run_info(
                f"task-{n}",
                True,
                f"{a}-{n}-{i}",
                a,
                flow_logs=[f"line {k}" for k in range(200)],
                flow_items=flow_items,
                run_summary={"status": "success"},
            )
# A pre-summary legacy entry is intentionally kept alongside new-format records.
with get_session_local()() as db:
    db.add(
        SignTaskRun(
            account_name="alpha",
            task_name="legacy",
            success=True,
            message="legacy",
            flow_items=json.dumps(flow_items),
            flow_logs='["legacy"]',
            flow_line_count=1,
        )
    )
    db.add(
        SignTaskRun(
            account_name="alpha",
            task_name="task-0",
            success=True,
            message="expired",
            created_at=now - timedelta(days=10),
            flow_logs="[]",
            flow_items="[]",
        )
    )
    db.add(
        RefreshToken(
            user_id=1, token_hash="expired", expires_at=now - timedelta(days=1)
        )
    )
    db.add(
        RefreshToken(
            user_id=1,
            token_hash="revoked-valid",
            expires_at=now + timedelta(days=1),
            revoked_at=now,
        )
    )
    db.add(AuditLog(action="preserve-audit", created_at=now - timedelta(days=365)))
    db.commit()
config_repo.save_config(
    "legacy",
    "alpha",
    {
        "sign_at": "09:00",
        "enabled": False,
        "chats": [{"chat_id": 123, "actions": [{"action": 1, "text": "/sign"}]}],
    },
)
headers = {"Authorization": f"Bearer {create_access_token({'sub': 'efficiency'})}"}
statements = []
loaded = []


@event.listens_for(engine, "before_cursor_execute")
def record_sql(conn, cursor, statement, parameters, context, executemany):
    statements.append(statement)


@event.listens_for(SignTaskRun, "load")
def record_load(target, context):
    loaded.append(target.id)


receipts = {}


def measured(client, name, path):
    statements.clear()
    loaded.clear()
    start = time.perf_counter()
    response = client.get(path, headers=headers)
    assert response.status_code == 200, response.text
    receipts[name] = {
        "status": response.status_code,
        "queries": len(statements),
        "history_rows_loaded": len(loaded),
        "response_bytes": len(response.content),
        "elapsed_ms": round((time.perf_counter() - start) * 1000, 2),
        "sql": list(statements),
    }
    assert not any(
        s.lstrip().upper().startswith(("DELETE", "UPDATE", "INSERT"))
        for s in statements
    ), name
    return response.json()


def run_http(client):
    for _ in range(100):
        if client.get("/readyz").status_code == 200:
            break
        time.sleep(0.05)
    assert client.get("/readyz").status_code == 200
    for label in ("cold", "warm"):
        rows = measured(client, f"list_{label}", "/api/sign-tasks?account_name=alpha")
        assert len(rows) == 11 and all(r["account_name"] == "alpha" for r in rows)
        assert receipts[f"list_{label}"]["queries"] <= 6
        assert not any(
            "flow_logs" in s.lower() and "case" not in s.lower() for s in statements
        )
    measured(client, "scheduler", "/api/sign-tasks/scheduler/status?account_name=alpha")
    assert not any("sign_task_runs" in s for s in statements)
    assert measured(
        client, "status", "/api/sign-tasks/task-0/status?account_name=alpha"
    ) == {"running": False}
    assert not any("sign_task_runs" in s for s in statements)
    for limit in (1, 30):
        rows = measured(
            client,
            f"history_{limit}",
            f"/api/sign-tasks/task-0/history?account_name=alpha&limit={limit}",
        )
        assert len(rows) == limit and all(r["message"] != "expired" for r in rows)
        assert receipts[f"history_{limit}"]["history_rows_loaded"] == limit
    rows = measured(client, "account_logs", "/api/accounts/alpha/logs?limit=12")
    assert len(rows) == 12 and receipts["account_logs"]["history_rows_loaded"] == 12
    response = client.get("/api/accounts/alpha/logs/export", headers=headers)
    assert response.status_code == 200 and len(response.content) > 1000
    receipts["export"] = {
        "status": response.status_code,
        "bytes": len(response.content),
    }
    # History remains authoritative if compact config last_run is missing/stale.
    config_repo.clear_last_run("task-0", "alpha")
    rows = measured(
        client, "summary_after_config_loss", "/api/sign-tasks?account_name=alpha"
    )
    assert (
        next(r for r in rows if r["name"] == "task-0")["last_run"]["message"]
        == "alpha-0-34"
    )
    # Use real CSRF acquisition for authenticated POSTs.
    login = client.post(
        "/api/auth/login", json={"username": "efficiency", "password": "Efficiency123!"}
    )
    assert login.status_code == 200, login.text
    csrf = client.cookies.get("tg-signer-csrf")
    post_headers = {**headers, "X-CSRF-Token": csrf or ""}

    def post(path, payload):
        return client.post(path, headers=post_headers, json=payload)

    for name in ("phone-cancel", "phone-expire"):
        payload = {"account_name": name, "phone_number": "+100"}
        response = post("/api/accounts/login/start", payload)
        assert response.status_code == 200, response.text
        result = response.json()
        assert not get_account_lock(name).locked()
        if name.endswith("cancel"):
            response = post(
                "/api/accounts/login/cancel",
                {**payload, "phone_code_hash": result["phone_code_hash"]},
            )
            assert response.status_code == 200, response.text
        else:
            time.sleep(1.3)
        assert not any(
            d.get("account_name") == name for d in telegram._login_sessions.values()
        )
        assert not transport["clients"][-1].is_connected
    payload = {"account_name": "replace", "phone_number": "+100"}
    old = post("/api/accounts/login/start", payload).json()
    new = post("/api/accounts/login/start", payload).json()
    post(
        "/api/accounts/login/cancel",
        {**payload, "phone_code_hash": old["phone_code_hash"]},
    )
    assert any(
        d.get("phone_code_hash") == new["phone_code_hash"]
        for d in telegram._login_sessions.values()
    )
    result = post(
        "/api/accounts/login/verify",
        {**payload, "phone_code": "12345", "phone_code_hash": new["phone_code_hash"]},
    )
    assert result.status_code == 200, result.text
    transport["needs_password"] = True
    payload = {"account_name": "twofactor", "phone_number": "+100"}
    started = post("/api/accounts/login/start", payload).json()
    verify = {
        **payload,
        "phone_code": "12345",
        "phone_code_hash": started["phone_code_hash"],
    }
    assert post("/api/accounts/login/verify", verify).status_code == 400
    assert (
        post("/api/accounts/login/verify", {**verify, "password": "wrong"}).status_code
        == 400
    )
    assert any(
        d.get("account_name") == "twofactor" for d in telegram._login_sessions.values()
    )
    assert (
        post(
            "/api/accounts/login/verify", {**verify, "password": "correct"}
        ).status_code
        == 200
    )
    transport["needs_password"] = False
    for delay in (0, 2):
        transport["connect_delay"] = delay
        response = post(
            "/api/accounts/status/check",
            {"account_names": ["alpha"], "timeout_seconds": 1},
        )
        assert response.status_code == 200, response.text
        assert not transport["clients"][-1].is_connected
        assert not get_account_lock("alpha").locked()
    transport["connect_delay"] = 0
    receipts["telegram"] = {
        "clients_created": len(transport["clients"]),
        "still_connected": sum(c.is_connected for c in transport["clients"]),
        "phone_sessions": len(telegram._login_sessions),
        "scope": "external Telegram transport faked",
    }
    assert receipts["telegram"]["still_connected"] == 0
    client.portal.call(concurrent_http, dict(client.cookies))
    client.portal.call(scheduler._job_maintenance)
    with get_session_local()() as db:
        assert db.query(SignTaskRun).filter_by(message="expired").count() == 0
        assert db.query(RefreshToken).filter_by(token_hash="expired").count() == 0
        assert db.query(RefreshToken).filter_by(token_hash="revoked-valid").count() == 1
        assert db.query(AuditLog).filter_by(action="preserve-audit").count() == 1
    assert upgrade_schema(engine) == upgrade_schema(engine)
    receipts["maintenance"] = {
        "expired_history_removed": True,
        "expired_tokens_removed": True,
        "audit_preserved": True,
    }
    from backend.core.config import get_settings

    settings = get_settings()
    previous = settings.audit_log_retention_days
    settings.audit_log_retention_days = 30
    try:
        client.portal.call(scheduler._job_maintenance)
        with get_session_local()() as db:
            assert db.query(AuditLog).filter_by(action="preserve-audit").count() == 0
    finally:
        settings.audit_log_retention_days = previous
    receipts["maintenance"]["explicit_audit_retention"] = True


async def concurrent_http(cookies):
    import httpx

    post_headers = {**headers, "X-CSRF-Token": cookies["tg-signer-csrf"]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=post_headers,
        cookies=cookies,
    ) as client:
        payload = {"account_name": "race", "phone_number": "+100"}
        transport["connect_delay"] = 0.05
        first, second = await asyncio.gather(
            *(client.post("/api/accounts/login/start", json=payload) for _ in range(2))
        )
        assert first.status_code == second.status_code == 200
        pending = next(
            d
            for d in telegram._login_sessions.values()
            if d.get("account_name") == "race"
        )
        current = pending["phone_code_hash"]
        old = next(
            r.json()["phone_code_hash"]
            for r in (first, second)
            if r.json()["phone_code_hash"] != current
        )
        stale = await client.post(
            "/api/accounts/login/verify",
            json={**payload, "phone_code_hash": old, "phone_code": "12345"},
        )
        assert stale.status_code == 400
        assert pending["client"].is_connected
        await client.post(
            "/api/accounts/login/cancel", json={**payload, "phone_code_hash": current}
        )
        assert not pending["client"].is_connected
        # Cancellation passes through the real HTTP app to the transport's connect.
        transport["connect_delay"] = 1
        cancelled = asyncio.create_task(
            client.post(
                "/api/accounts/login/start",
                json={"account_name": "cancel-inflight", "phone_number": "+100"},
            )
        )
        await asyncio.sleep(0.1)
        cancelled.cancel()
        try:
            await cancelled
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0)
        assert not get_account_lock("cancel-inflight").locked()
        assert not transport["clients"][-1].is_connected
        transport["connect_delay"] = 0
        # Waiting on someone else's execution lock is part of the probe budget.
        lock = get_account_lock("alpha")
        await lock.acquire()
        try:
            reply = await client.post(
                "/api/accounts/status/check",
                json={"account_names": ["alpha"], "timeout_seconds": 1},
            )
            assert reply.json()["results"][0]["code"] == "TIMEOUT"
            assert lock.locked()
        finally:
            lock.release()
        qr = await client.post(
            "/api/accounts/qr/start", json={"account_name": "qr-e2e"}
        )
        assert qr.status_code == 200, qr.text
        login_id = qr.json()["login_id"]
        session = telegram._qr_login_sessions[login_id]
        session["scan_seen"] = True
        session["status"] = "scanned_wait_confirm"
        transport["qr_delay"] = 0.2
        await asyncio.gather(
            *(
                client.get("/api/accounts/qr/status", params={"login_id": login_id})
                for _ in range(3)
            )
        )
        assert transport["qr_max_active"] == 1
        await client.post("/api/accounts/qr/cancel", json={"login_id": login_id})
        assert not session["client"].is_connected
        transport["qr_delay"] = 0
    receipts["concurrency"] = {
        "stale_verify_isolated": True,
        "cancelled_connect_released": True,
        "probe_lock_budget": True,
        "max_qr_rpcs": transport["qr_max_active"],
    }


async def event_wait():
    finished = asyncio.Event()
    runner = SimpleNamespace(finished=finished, history_limit=0, result="complete")
    asyncio.get_running_loop().call_later(0.02, finished.set)
    start = time.perf_counter()
    result = await SignEventRunner._wait_finished(runner)
    elapsed = time.perf_counter() - start
    assert result == "complete" and elapsed < 0.15
    receipts["event_wait"] = {"elapsed_ms": round(elapsed * 1000, 2)}
    finished.clear()
    rescues = []

    async def rescue():
        rescues.append(time.perf_counter())
        finished.set()

    runner.history_limit = 1
    runner.history_rescue_interval = 0.25
    runner.history_rescue_suspended = False
    runner._last_history_rescue_at = asyncio.get_running_loop().time()
    runner._walk_history_rescue_until_finished = rescue
    start = time.perf_counter()
    await SignEventRunner._wait_finished(runner)
    assert len(rescues) == 1 and rescues[0] - start >= 0.24
    finished.clear()
    runner.history_rescue_suspended = True
    asyncio.get_running_loop().call_later(0.02, finished.set)
    await SignEventRunner._wait_finished(runner)
    assert len(rescues) == 1
    finished.clear()
    pending = asyncio.create_task(SignEventRunner._wait_finished(runner))
    await asyncio.sleep(0)
    pending.cancel()
    try:
        await pending
        raise AssertionError("completion wait swallowed cancellation")
    except asyncio.CancelledError:
        pass
    receipts["event_wait"].update(
        rescue_deadline=True, suspended_completion=True, cancellation=True
    )


async def ai_lifecycle():
    # Failure scenarios are recorded in resource_efficiency_scenarios.txt.
    # Isolate only worker scheduling/Telegram and the external AI transport.

    clients = []
    mode = {"value": "success"}

    class ExternalAI:
        def __init__(self, **kwargs):
            self.closed = 0
            self.requests = 0
            self.chat = SimpleNamespace(completions=self)
            clients.append(self)

        async def create(self, **kwargs):
            self.requests += 1
            if mode["value"] == "error":
                raise RuntimeError("synthetic AI failure")
            if mode["value"] == "cancel":
                raise asyncio.CancelledError()
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
            )

        async def close(self):
            self.closed += 1

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            await self.close()

    class IsolatedWorker(UserSigner):
        async def normal_run(self, *args, **kwargs):
            first = self.get_ai_tools()
            assert first is self.get_ai_tools()
            await first.get_reply("test", "one")
            await self.get_ai_tools().get_reply("test", "two")

    worker = object.__new__(IsolatedWorker)
    worker.app = SimpleNamespace(in_memory=False, session_string=None)
    worker._ai_tools = None
    worker.ensure_ai_cfg = lambda: {"api_key": "synthetic"}
    with patch("openai.AsyncOpenAI", ExternalAI):
        for outcome in ("success", "error", "cancel", "success"):
            mode["value"] = outcome
            before = len(clients)
            try:
                await worker.run(only_once=True)
                assert outcome == "success"
            except (RuntimeError, asyncio.CancelledError):
                assert outcome != "success"
            assert len(clients) == before + 1
            assert clients[-1].closed == 1 and worker._ai_tools is None
        assert clients[0].requests == clients[-1].requests == 2
        get_config_service().save_ai_config("synthetic")
        import httpx

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers=headers,
        ) as client:
            login = await client.post(
                "/api/auth/login",
                json={"username": "efficiency", "password": "Efficiency123!"},
            )
            assert login.status_code == 200
            for outcome in ("success", "error"):
                mode["value"] = outcome
                response = await client.post(
                    "/api/config/ai/test",
                    headers={"X-CSRF-Token": client.cookies["tg-signer-csrf"]},
                )
                assert response.status_code == 200, response.text
                assert response.json()["success"] == (outcome == "success")
                assert clients[-1].closed == 1
    receipts["ai_lifecycle"] = {
        "reuse": True,
        "success_error_cancel_closed": True,
        "new_run_new_client": True,
        "connection_test_closed": True,
    }


with patch("pyrogram.Client", FakeTelegram):
    if args.serve:
        import uvicorn
        from fastapi import Depends, Request
        from backend.core.auth import get_current_user

        metrics = {"paths": Counter()}

        @app.middleware("http")
        async def count_requests(request, call_next):
            metrics["paths"][request.url.path] += 1
            return await call_next(request)

        @app.post("/__e2e/control")
        async def control(request: Request, user=Depends(get_current_user)):
            changes = await request.json()
            for key in ("connect_delay", "qr_delay", "verify_delay"):
                if key in changes:
                    transport[key] = float(changes[key])
            if changes.get("scan"):
                for session in telegram._qr_login_sessions.values():
                    session.update(scan_seen=True, status="scanned_wait_confirm")
            if changes.get("add_history"):
                service._save_run_info(
                    "task-0", True, "browser-completed", "alpha", flow_items=flow_items
                )
            if changes.get("reset_metrics"):
                metrics["paths"].clear()
            return {
                "paths": dict(metrics["paths"]),
                "phone_sessions": len(telegram._login_sessions),
                "qr_sessions": len(telegram._qr_login_sessions),
                "qr_max_active": transport["qr_max_active"],
                "connected": sum(c.is_connected for c in transport["clients"]),
            }

        # Static export served through normal routes from the local build.
        import backend.main as main
        from fastapi.staticfiles import StaticFiles

        main.WEB_DIR = ROOT / "frontend" / "out"
        if (main.WEB_DIR / "_next").exists():
            app.router.routes.insert(
                0,
                __import__("starlette.routing", fromlist=["Mount"]).Mount(
                    "/_next", app=StaticFiles(directory=main.WEB_DIR / "_next")
                ),
            )
        (args.output / "browser-session.json").write_text(
            json.dumps(
                {
                    "token": headers["Authorization"][7:],
                    "username": "efficiency",
                    "password": "Efficiency123!",
                }
            )
        )
        uvicorn.run(app, host="127.0.0.1", port=args.serve)
    else:
        try:
            with TestClient(app) as client:
                run_http(client)
            asyncio.run(event_wait())
            asyncio.run(ai_lifecycle())
            receipts["passed"] = True
        finally:
            (args.output / "resource-e2e.json").write_text(
                json.dumps(receipts, indent=2)
            )
        print(
            json.dumps(
                {
                    k: {a: b for a, b in v.items() if a != "sql"}
                    if isinstance(v, dict)
                    else v
                    for k, v in receipts.items()
                },
                indent=2,
            )
        )
