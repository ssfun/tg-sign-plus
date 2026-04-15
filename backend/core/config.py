from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from backend.utils.storage import get_initial_data_dir, get_writable_base_dir

try:
    from pydantic.v1 import BaseSettings
except ImportError:
    from pydantic import BaseSettings


# 生成或获取持久化的密钥
def get_default_secret_key() -> str:
    """获取默认密钥，优先使用环境变量，否则自动生成并持久化"""
    import logging
    import secrets

    logger = logging.getLogger("backend.security")

    # 优先使用环境变量
    env_secret = os.getenv("APP_SECRET_KEY")
    if env_secret and env_secret.strip():
        return env_secret.strip()

    # 尝试从持久化文件读取
    try:
        secret_file = get_writable_base_dir() / ".secret_key"
        if secret_file.exists():
            stored_key = secret_file.read_text().strip()
            if stored_key:
                return stored_key
    except Exception as e:
        logger.warning(f"无法读取持久化密钥文件: {e}")

    # 生成新密钥并持久化
    try:
        new_key = secrets.token_urlsafe(32)
        secret_file = get_writable_base_dir() / ".secret_key"
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        secret_file.write_text(new_key)
        secret_file.chmod(0o600)

        logger.warning(
            f"自动生成 JWT 密钥并保存到 {secret_file}，"
            "生产环境请设置 APP_SECRET_KEY 环境变量"
        )
        return new_key
    except Exception as e:
        logger.error(f"无法生成或保存密钥文件: {e}")
        # 最后的兜底方案：使用固定默认值（不安全）
        logger.critical(
            "使用不安全的默认密钥！生产环境必须设置 APP_SECRET_KEY 环境变量"
        )
        return "tg-signer-default-secret-key-please-change-in-production-2024"


class Settings(BaseSettings):
    app_name: str = "tg-signer-panel"
    host: str = os.getenv("APP_HOST", "127.0.0.1")
    port: int = 3000

    # 使用函数获取默认密钥
    secret_key: str = get_default_secret_key()
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14
    refresh_cookie_name: str = "tg-signer-refresh"
    refresh_cookie_secure: bool = True
    refresh_cookie_samesite: str = "lax"
    refresh_cookie_path: str = "/api"
    cors_allow_origin_regex: str = r"https?://(localhost|127\.0\.0\.1)(:\d+)?$"

    timezone: str = os.getenv("TZ", "Asia/Hong_Kong")
    data_dir: Path = get_initial_data_dir()
    database_url: str
    signer_workdir: Optional[Path] = None
    session_dir: Optional[Path] = None
    logs_dir: Optional[Path] = None

    class Config:
        env_file = ".env"
        env_prefix = "APP_"
        case_sensitive = False

    def resolve_workdir(self) -> Path:
        return self.signer_workdir or self.resolve_base_dir() / ".signer"

    def resolve_session_dir(self) -> Path:
        return self.session_dir or self.resolve_base_dir() / "sessions"

    def resolve_logs_dir(self) -> Path:
        return self.logs_dir or self.resolve_base_dir() / "logs"

    def resolve_base_dir(self) -> Path:
        if self.data_dir and str(self.data_dir) != "/data":
            return self.data_dir
        return get_writable_base_dir()


@lru_cache()
def get_settings() -> Settings:
    return Settings()

