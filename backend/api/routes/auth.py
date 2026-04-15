from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.core import auth as auth_core
from backend.core.auth import (
    authenticate_user,
    create_access_token,
    create_refresh_token_session,
    get_refresh_token_from_request,
    rotate_refresh_token,
    set_refresh_cookie,
    verify_refresh_token,
    verify_totp,
    clear_refresh_cookie,
    revoke_refresh_token,
)
from backend.core.audit import log_audit, get_client_ip
from backend.core.config import get_settings
from backend.core.database import get_db
from backend.core.rate_limit import limiter
from backend.core.security import verify_password
from backend.models.user import User
from backend.schemas.auth import LoginRequest, TokenResponse, UserOut

router = APIRouter()
settings = get_settings()


class ResetTOTPRequest(BaseModel):
    """重置 TOTP 请求（通过密码验证）"""

    username: str
    password: str


class ResetTOTPResponse(BaseModel):
    """重置 TOTP 响应"""

    success: bool
    message: str


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
def login(
    request: Request,
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    user = authenticate_user(db, payload.username, payload.password)
    if not user:
        # 记录登录失败
        log_audit(
            db=db,
            action="login_failed",
            username=payload.username,
            ip_address=get_client_ip(request),
            user_agent=request.headers.get("User-Agent"),
            status="failure",
            details={"reason": "invalid_credentials"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    if user.totp_secret:
        if not payload.totp_code or not verify_totp(
            user.totp_secret, payload.totp_code
        ):
            # 记录 TOTP 验证失败
            log_audit(
                db=db,
                action="login_failed",
                user=user,
                ip_address=get_client_ip(request),
                user_agent=request.headers.get("User-Agent"),
                status="failure",
                details={"reason": "invalid_totp"},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="TOTP_REQUIRED_OR_INVALID",
            )

    # 登录成功
    access_token = create_access_token(data={"sub": user.username})
    refresh_token = create_refresh_token_session(db, user)
    set_refresh_cookie(response, refresh_token)

    # 记录登录成功
    log_audit(
        db=db,
        action="login",
        user=user,
        ip_address=get_client_ip(request),
        user_agent=request.headers.get("User-Agent"),
        status="success",
    )

    return TokenResponse(
        access_token=access_token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("10/minute")
def refresh_access_token(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    refresh_token = get_refresh_token_from_request(request)
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing",
        )

    refresh_session = verify_refresh_token(db, refresh_token)
    if refresh_session is None:
        clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token invalid",
        )

    user = db.query(User).filter(User.id == refresh_session.user_id).first()
    if user is None:
        clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    new_refresh_token = rotate_refresh_token(db, refresh_session)
    set_refresh_cookie(response, new_refresh_token)
    access_token = create_access_token(data={"sub": user.username})
    return TokenResponse(
        access_token=access_token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(auth_core.get_current_user_optional),
):
    refresh_token = get_refresh_token_from_request(request)
    if refresh_token:
        revoke_refresh_token(db, refresh_token)
    clear_refresh_cookie(response)

    # 记录登出
    if current_user:
        log_audit(
            db=db,
            action="logout",
            user=current_user,
            ip_address=get_client_ip(request),
            user_agent=request.headers.get("User-Agent"),
            status="success",
        )

    response.status_code = status.HTTP_204_NO_CONTENT
    return None


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(auth_core.get_current_user)):
    return current_user


@router.post("/reset-totp", response_model=ResetTOTPResponse)
@limiter.limit("5/minute")
def reset_totp(request: Request, payload: ResetTOTPRequest, db: Session = Depends(get_db)):
    """
    强制重置 TOTP（不需要 TOTP 验证码，只需要密码）

    用于解决用户启用了 TOTP 但无法登录的问题。
    需要提供正确的用户名和密码。
    """
    # 验证用户名和密码
    user = db.query(User).filter(User.username == payload.username).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误"
        )

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误"
        )

    # 如果没有启用 TOTP，提示无需重置
    if not user.totp_secret:
        return ResetTOTPResponse(success=True, message="该用户未启用两步验证，无需重置")

    # 清除 TOTP secret
    user.totp_secret = None
    db.commit()

    return ResetTOTPResponse(success=True, message="两步验证已重置，现在可以正常登录")
