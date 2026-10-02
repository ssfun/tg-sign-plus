"""HTTP/WebSocket resource acceptance; see resource_convergence.md for failures."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta
import gc
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import weakref

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--serve", type=int)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
data = tempfile.TemporaryDirectory(prefix="tg-convergence-")
os.environ.update(APP_DATA_DIR=data.name, APP_DATABASE_URL=f"sqlite:///{data.name}/test.sqlite",
                  APP_SECRET_KEY="isolated-convergence-secret", TG_API_ID="1234", TG_API_HASH="synthetic")

import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import event
import backend.models
from backend.main import app
from backend.core.database import get_engine, get_session_local
from backend.core.schema_migrator import upgrade_schema
from backend.core.auth import create_access_token
from backend.core.csrf import create_csrf_token
from backend.core.security import hash_password, verify_password
from backend.models.user import User
from backend.models.account_session import AccountSession
from backend.models.account_chat_cache import AccountChatCacheMeta, AccountChatCacheItem
from backend.services import telegram
from backend.services.sign_tasks import get_sign_task_service
from backend.services.config import get_config_service
from backend.utils.account_locks import get_account_lock
from pyrogram.enums import ChatType
from pyrogram.types import Message, Chat, User as TelegramUser
from tg_signer.core import UserSigner

engine = get_engine()
upgrade_schema(engine)
with get_session_local()() as db:
    db.add(User(username="review", password_hash=hash_password("Review123!")))
    for i in range(25):
        db.add(AccountSession(account_name=f"acct{i:02}", session_string="synthetic", remark=f"Remark {i}"))
    db.add(AccountChatCacheMeta(account_name="acct00", last_cached_at=datetime.utcnow()))
    db.flush()
    for i in range(200):
        db.add(AccountChatCacheItem(account_name="acct00", chat_id=i+1, title=f"Chat {i:03}", chat_type="private"))
    db.commit()
get_config_service().save_telegram_config(api_id="1234", api_hash="synthetic")
service = get_sign_task_service()
queries, loads = [], []
receipts = {}
transport = {"count": 200, "calls": 0, "fail": False, "held": []}


@event.listens_for(engine, "before_cursor_execute")
def record_query(conn, cursor, stmt, params, context, many):
    if stmt.lstrip().upper().startswith("SELECT"):
        queries.append(stmt)


@event.listens_for(AccountChatCacheItem, "load")
def record_load(target, context):
    loads.append(target.chat_id)


class ChatTransport:
    async def __aenter__(self):
        transport["calls"] += 1
        transport["held"].append(engine.pool.checkedout())
        await asyncio.sleep(.01)
        if transport["fail"]:
            raise RuntimeError("synthetic transport unavailable")
        return self

    async def __aexit__(self, *args):
        pass

    async def get_me(self):
        return SimpleNamespace(id=1)

    async def get_dialogs(self):
        for i in range(transport["count"]):
            yield SimpleNamespace(chat=SimpleNamespace(id=i+1, title=f"Chat {i:03}", username=None,
                                                       first_name=None, type=ChatType.PRIVATE))


def transport_factory(**kwargs):
    return ChatTransport()


token = create_access_token({"sub": "review"})
headers = {"Authorization": f"Bearer {token}"}


def run_http():
    with TestClient(app) as http:
        csrf = create_csrf_token()
        http.cookies.set("tg-signer-csrf", csrf)
        http.headers.update({**headers, "X-CSRF-Token": csrf})
        telegram.get_telegram_service()._accounts_cache = None
        telegram._login_sessions["pending"] = {"account_name": "acct24"}
        queries.clear()
        response = http.get("/api/accounts")
        assert response.status_code == 200, response.text
        accounts = response.json()["accounts"]
        account_queries = [q for q in queries if "account_sessions" in q]
        assert len(accounts) == 24 and accounts[0]["remark"] == "Remark 0"
        assert len(account_queries) == 1, len(account_queries)
        assert "session_string" not in account_queries[0], account_queries[0]
        telegram._login_sessions.pop("pending")
        receipts["account_cold"] = {"account_selects": len(account_queries), "visible": len(accounts)}

        with patch("backend.services.sign_task_chat_cache._get_client_factory", return_value=transport_factory):
            loads.clear()
            response = http.post("/api/sign-tasks/chats/acct00/refresh?include_items=false")
            assert response.status_code == 200, response.text
            assert response.json()["items"] == [] and response.json()["count"] == 200
            assert not loads, len(loads)
            assert transport["held"] == [0], transport["held"]
            receipts["refresh"] = {"chat_objects_loaded": len(loads), "connections_held": transport["held"]}
            loads.clear()
            response = http.get("/api/sign-tasks/chats/acct00")
            assert response.status_code == 200 and len(response.json()["items"]) == 200
            assert len(loads) == 200
            pages = []
            for offset in (0, 50, 100, 150):
                loads.clear()
                response = http.get(f"/api/sign-tasks/chats/acct00/search?limit=50&offset={offset}")
                assert response.status_code == 200 and response.json()["total"] == 200
                assert len(loads) == 50
                pages.extend(item["id"] for item in response.json()["items"])
            assert len(set(pages)) == 200
            response = http.get("/api/sign-tasks/chats/acct00/search?q=Chat%20199")
            assert response.json()["items"][0]["id"] == 200
            receipts["pagination"] = {"pages": 4, "items_per_page": 50, "unique_ids": len(set(pages))}

            lock = get_account_lock("acct00")
            http.portal.call(lock.acquire)
            try:
                assert http.post("/api/sign-tasks/chats/acct00/refresh").status_code == 409
                assert http.get("/api/sign-tasks/chats/acct00?ensure_exists=true").json()["count"] == 200
            finally:
                http.portal.call(lock.release)
            transport["fail"] = True
            assert http.post("/api/sign-tasks/chats/acct00/refresh").status_code == 409
            assert http.get("/api/sign-tasks/chats/acct00").json()["count"] == 200
            transport["fail"] = False
            with get_session_local()() as db:
                db.query(AccountChatCacheMeta).filter_by(account_name="acct00").update(
                    {"last_cached_at": datetime.utcnow()-timedelta(days=2)})
                db.commit()
            calls = transport["calls"]
            assert http.get("/api/sign-tasks/chats/acct00?auto_refresh_if_expired=true&include_items=false").status_code == 200
            assert transport["calls"] == calls + 1
            transport["count"] = 0
            assert http.post("/api/sign-tasks/chats/acct01/refresh?include_items=false").json()["count"] == 0
            calls = transport["calls"]
            assert http.get("/api/sign-tasks/chats/acct01?ensure_exists=true&include_items=false").json()["count"] == 0
            assert transport["calls"] == calls
            transport["count"] = 200

        ws_held = []
        def snapshot(*a, **kw):
            ws_held.append(engine.pool.checkedout())
            return 0, []
        with patch.object(service, "is_task_running", return_value=False), patch.object(service, "get_active_logs_snapshot", side_effect=snapshot):
            with http.websocket_connect(f"/api/sign-tasks/ws/demo?account_name=acct00&token={token}") as ws:
                assert ws.receive_json()["type"] == "done"
        assert ws_held == [0], ws_held
        receipts["websocket"] = {"connections_held": ws_held}
        assert http.get("/api/accounts", headers={"Authorization": "Bearer invalid"}).status_code == 401
        assert http.get("/api/accounts", headers={"Authorization": "Bearer "+create_access_token({"sub":"absent"})}).status_code == 401

        response = http.put("/api/user/password", json={"old_password":"Review123!", "new_password":"Updated123!"})
        assert response.status_code == 200, response.text
        response = http.put("/api/user/username", json={"password":"Updated123!", "new_username":"renamed"})
        assert response.status_code == 200, response.text
        http.headers["Authorization"] = "Bearer " + response.json()["access_token"]
        response = http.post("/api/user/totp/setup")
        assert response.status_code == 200, response.text
        secret = response.json()["secret"]
        response = http.post("/api/user/totp/enable", json={"totp_code":pyotp.TOTP(secret).now()})
        assert response.status_code == 200, response.text
        with get_session_local()() as db:
            user = db.query(User).filter_by(username="renamed").one()
            assert verify_password("Updated123!", user.password_hash) and user.totp_secret == secret
        receipts["user_mutations"] = {"password": True, "username": True, "totp": True}


async def run_messages():
    signer = UserSigner.__new__(UserSigner)
    signer.context = signer.ensure_ctx()
    logs = []
    signer.log = lambda text, **kw: logs.append(text)
    refs = []
    for i in range(500):
        message = Message(id=i+1, chat=Chat(id=123, type=ChatType.PRIVATE),
                          from_user=TelegramUser(id=1, first_name="synthetic"), text="synthetic")
        refs.append(weakref.ref(message))
        await signer.on_message(None, message)
    del message
    gc.collect()
    assert not any(ref() is not None for ref in refs)
    delivered = []
    class Runner:
        async def handle_message(self, message):
            delivered.append(message.id)
    signer.context.event_runners[123] = Runner()
    message = Message(id=501, chat=Chat(id=123, type=ChatType.PRIVATE), text="success")
    await signer.on_message(None, message)
    await signer.on_edited_message(None, message)
    await asyncio.gather(*signer.context.event_tasks)
    await signer._drain_event_tasks()
    assert delivered == [501, 501] and not signer.context.event_tasks
    from backend.services.sign_task_executor import SignTaskExecutor
    assert SignTaskExecutor._extract_last_reply(logs) == "success", logs
    receipts["messages"] = {"inactive_retained": 0, "new_and_edited_delivered": len(delivered)}


if not args.serve:
    run_http()
    asyncio.run(run_messages())
    (args.output / "resource-convergence.json").write_text(json.dumps(receipts, indent=2))
    print(json.dumps(receipts, indent=2))
else:
    import backend.main as main
    from fastapi import Request, Depends
    from backend.core.auth import get_current_user_readonly
    from fastapi.staticfiles import StaticFiles
    from starlette.routing import Mount
    import uvicorn
    controls = {"search_delay": 0.0, "fail_refresh": False, "requests": []}

    @app.middleware("http")
    async def browser_metrics(request, call_next):
        if request.url.path.startswith("/api/sign-tasks/chats/"):
            controls["requests"].append(str(request.url.path) + "?" + str(request.url.query))
            if request.url.path.endswith("/search"):
                await asyncio.sleep(controls["search_delay"])
        return await call_next(request)

    @app.post("/__e2e/control")
    async def control(request: Request, user=Depends(get_current_user_readonly)):
        values = await request.json()
        if values.get("reset"):
            controls["requests"].clear()
        if "search_delay" in values:
            controls["search_delay"] = float(values["search_delay"])
        if "fail_refresh" in values:
            transport["fail"] = bool(values["fail_refresh"])
        return controls

    main.WEB_DIR = ROOT / "frontend" / "out"
    app.router.routes.insert(0, Mount("/_next", app=StaticFiles(directory=main.WEB_DIR / "_next")))
    (args.output / "browser-session.json").write_text(json.dumps({"token": token}))
    with patch("backend.services.sign_task_chat_cache._get_client_factory", return_value=transport_factory):
        uvicorn.run(app, host="127.0.0.1", port=args.serve)
