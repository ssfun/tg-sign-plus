from datetime import timedelta
from types import SimpleNamespace

import pyotp
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.routes.auth import router as auth_router
from backend.api.routes.sign_tasks import router as task_router
from backend.core.auth import create_access_token
from backend.core.csrf import CSRF_HEADER_NAME, enforce_csrf
from backend.core.database import Base, get_db
from backend.core.security import hash_password
from backend.models.user import User
from backend.services.sign_tasks import get_sign_task_service
import backend.models  # noqa: F401


@pytest.fixture
def panel():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add(User(username="admin", password_hash=hash_password("Regression123!"), totp_secret="JBSWY3DPEHPK3PXP"))
        db.commit()
    app = FastAPI()
    app.include_router(auth_router, prefix="/api/auth")
    app.include_router(task_router, prefix="/api/sign-tasks")
    @app.middleware("http")
    async def csrf(request: Request, call_next):
        try:
            enforce_csrf(request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)
    def session():
        with sessions() as db:
            yield db
    calls = []
    service = SimpleNamespace(
        get_task=lambda task, account: {"name": task} if (task, account) == ("sign", "test-account") else None,
        is_task_running=lambda task, account_name: calls.append((task, account_name)) or True,
    )
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_sign_task_service] = lambda: service
    with TestClient(app) as client:
        yield client, calls
    engine.dispose()


def test_totp_refresh_csrf_and_logout(panel):
    client, _ = panel
    credentials = {"username": "admin", "password": "Regression123!"}
    assert client.post("/api/auth/login", json=credentials).status_code == 401
    response = client.post("/api/auth/login", json={**credentials, "totp_code": pyotp.TOTP("JBSWY3DPEHPK3PXP").now()})
    assert response.status_code == 200
    refresh = client.cookies.get("tg-signer-refresh")
    assert refresh
    assert "httponly" in response.headers["set-cookie"].lower()
    assert client.post("/api/auth/refresh").status_code == 403
    csrf = client.cookies.get("tg-signer-csrf")
    response = client.post("/api/auth/refresh", headers={CSRF_HEADER_NAME: csrf})
    assert response.status_code == 200
    assert client.cookies.get("tg-signer-refresh") != refresh
    csrf = client.cookies.get("tg-signer-csrf")
    assert client.post("/api/auth/logout", headers={CSRF_HEADER_NAME: csrf}).status_code == 204
    assert client.cookies.get("tg-signer-refresh") is None


def test_task_status_is_authenticated_and_account_scoped(panel):
    client, calls = panel
    path = "/api/sign-tasks/sign/status?account_name=test-account"
    assert client.get(path).status_code == 401
    expired = create_access_token({"sub": "admin"}, expires_delta=timedelta(seconds=-1))
    assert client.get(path, headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    token = create_access_token({"sub": "admin"})
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get(path, headers=headers).json() == {"running": True}
    assert calls == [("sign", "test-account")]
    assert client.get("/api/sign-tasks/sign/status?account_name=other", headers=headers).status_code == 404
