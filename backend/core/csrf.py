"""CSRF 保护配置

提供 CSRF 保护中间件配置。
"""

from __future__ import annotations

from fastapi_csrf_protect import CsrfProtect
from pydantic import BaseModel

from backend.core.config import get_settings


class CsrfSettings(BaseModel):
    """CSRF 配置"""
    secret_key: str
    cookie_key: str = "fastapi-csrf-token"
    cookie_path: str = "/"
    cookie_domain: str | None = None
    cookie_secure: bool = True
    cookie_samesite: str = "lax"
    header_name: str = "X-CSRF-Token"
    header_type: str | None = None
    httponly: bool = False  # CSRF token 需要被 JavaScript 读取


@CsrfProtect.load_config
def get_csrf_config():
    """加载 CSRF 配置"""
    settings = get_settings()
    return CsrfSettings(secret_key=settings.secret_key)
