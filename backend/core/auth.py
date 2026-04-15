from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

import pyotp
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.database import get_db
from backend.core.security import verify_password
from backend.models.refresh_token import RefreshToken
from backend.models.user import User
from backend.utils.timezone import utcnow_naive

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

settings = get_settings()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = utcnow_naive() + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm="HS256")


def verify_totp(secret: str, code: str) -> bool:
    try:
        if not isinstance(code, str):
            return False
        code = code.strip().replace(" ", "")
        if not code:
            return False
        totp = pyotp.TOTP(secret)
        raw_window = os.getenv("APP_TOTP_VALID_WINDOW")
        raw_window = raw_window.strip() if isinstance(raw_window, str) else ""
        try:
            valid_window = int(raw_window) if raw_window else 1
        except ValueError:
            valid_window = 1
        if valid_window < 0:
            valid_window = 0
        return totp.verify(code, valid_window=valid_window)
    except Exception:
        return False


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    user = db.query(User).filter(User.username == username).first()
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def _access_token_payload(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        username = payload.get("sub")
        if username is None:
            return None
        return payload
    except JWTError:
        return None


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = _access_token_payload(token)
    if payload is None:
        raise credentials_exception
    username: str = payload.get("sub")  # type: ignore[assignment]
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    return user


# OAuth2 scheme that doesn't auto-error on missing token
oauth2_scheme_optional = OAuth2PasswordBearer(
    tokenUrl="/api/auth/login", auto_error=False
)


def get_current_user_optional(
    token: Optional[str] = Depends(oauth2_scheme_optional),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """获取当前用户，如果无法认证则返回 None（不抛出异常）"""
    if not token:
        return None
    return verify_token(token, db)


def verify_token(token: str, db: Session) -> Optional[User]:
    """验证 Token 并返回用户对象"""
    payload = _access_token_payload(token)
    if payload is None:
        return None
    username: str = payload.get("sub")  # type: ignore[assignment]
    user = db.query(User).filter(User.username == username).first()
    return user


def _hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def create_refresh_token_session(db: Session, user: User) -> str:
    token = create_refresh_token()
    token_hash = _hash_refresh_token(token)
    now = utcnow_naive()
    session = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=now + timedelta(days=settings.refresh_token_expire_days),
        last_used_at=now,
    )
    db.add(session)
    db.commit()
    return token


def get_refresh_token_from_request(request: Request) -> Optional[str]:
    token = request.cookies.get(settings.refresh_cookie_name)
    if not isinstance(token, str):
        return None
    token = token.strip()
    return token or None


def verify_refresh_token(db: Session, token: str) -> Optional[RefreshToken]:
    token_hash = _hash_refresh_token(token)
    session = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if session is None:
        return None
    if session.revoked_at is not None:
        return None
    if session.expires_at <= utcnow_naive():
        return None
    return session


def rotate_refresh_token(db: Session, refresh_session: RefreshToken) -> str:
    new_token = create_refresh_token()
    new_hash = _hash_refresh_token(new_token)
    now = utcnow_naive()
    refresh_session.revoked_at = now
    refresh_session.replaced_by_token_hash = new_hash
    replacement = RefreshToken(
        user_id=refresh_session.user_id,
        token_hash=new_hash,
        expires_at=now + timedelta(days=settings.refresh_token_expire_days),
        last_used_at=now,
    )
    db.add(replacement)
    db.commit()
    return new_token


def revoke_refresh_token(db: Session, token: str) -> None:
    token_hash = _hash_refresh_token(token)
    session = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if session is None or session.revoked_at is not None:
        return
    session.revoked_at = utcnow_naive()
    db.commit()


def revoke_user_refresh_tokens(db: Session, user_id: int) -> None:
    now = utcnow_naive()
    sessions = (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .all()
    )
    for session in sessions:
        session.revoked_at = now
    if sessions:
        db.commit()


def set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
        path=settings.refresh_cookie_path,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,
    )


def get_user_from_refresh_request(request: Request, db: Session) -> Optional[User]:
    token = get_refresh_token_from_request(request)
    if not token:
        return None
    refresh_session = verify_refresh_token(db, token)
    if refresh_session is None:
        return None
    return db.query(User).filter(User.id == refresh_session.user_id).first()
