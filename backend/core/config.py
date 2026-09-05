from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from backend.utils.storage import get_initial_data_dir, get_writable_base_dir

try:
    from pydantic.v1 import BaseSettings, Field, root_validator, validator
except ImportError:
    from pydantic import BaseSettings, Field, root_validator, validator


def get_default_base_dir() -> Path:
    data_dir = get_initial_data_dir()
    if str(data_dir) != "/data":
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir
    return get_writable_base_dir()


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
        secret_file = get_default_base_dir() / ".secret_key"
        if secret_file.exists():
            stored_key = secret_file.read_text().strip()
            if stored_key:
                return stored_key
            raise RuntimeError("持久化密钥文件为空，请设置 APP_SECRET_KEY")
    except Exception as e:
        raise RuntimeError(
            "无法读取持久化密钥，请修复文件权限或设置 APP_SECRET_KEY"
        ) from e

    # 生成新密钥并持久化
    try:
        new_key = secrets.token_urlsafe(32)
        secret_file = get_default_base_dir() / ".secret_key"
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        # Create with restrictive permissions; never overwrite another process's key.
        fd = os.open(secret_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(new_key)

        logger.warning(
            f"自动生成 JWT 密钥并保存到 {secret_file}，"
            "生产环境请设置 APP_SECRET_KEY 环境变量"
        )
        return new_key
    except Exception as e:
        raise RuntimeError(
            "无法持久化安全密钥，请修复目录权限或设置 APP_SECRET_KEY"
        ) from e


def get_default_database_url() -> str:
    base_dir = get_default_base_dir()
    return f"sqlite:///{base_dir / 'db.sqlite'}"


def get_default_timezone() -> str:
    return os.getenv("TZ", "Asia/Hong_Kong")


class Settings(BaseSettings):
    app_name: str = "tg-signer-panel"
    host: str = "127.0.0.1"
    port: int = 3000

    # 使用函数获取默认密钥
    secret_key: str = Field(default_factory=get_default_secret_key)

    @validator("secret_key", always=True)
    def validate_secret_key(cls, value):
        value = value.strip()
        if (
            not value
            or value == "tg-signer-default-secret-key-please-change-in-production-2024"
        ):
            raise ValueError("APP_SECRET_KEY 不能为空或使用旧版公开默认密钥")
        return value

    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14
    refresh_cookie_name: str = "tg-signer-refresh"
    refresh_cookie_secure: bool = False
    refresh_cookie_samesite: str = "lax"
    refresh_cookie_path: str = "/api"
    cors_allow_origin_regex: str = r"https?://(localhost|127\.0\.0\.1)(:\d+)?$"
    allow_password_totp_reset: bool = False

    timezone: str = Field(default_factory=get_default_timezone)
    data_dir: Path = Field(default_factory=get_initial_data_dir)
    database_url: str = Field(default_factory=get_default_database_url)
    signer_workdir: Optional[Path] = None
    session_dir: Optional[Path] = None
    logs_dir: Optional[Path] = None

    @root_validator(pre=True)
    def _database_url_env_alias(cls, values):
        if values.get("database_url"):
            return values
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            values["database_url"] = database_url
        return values

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
