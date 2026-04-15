from __future__ import annotations

from datetime import datetime
from typing import Callable

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from backend.core.database import Base

LATEST_SCHEMA_VERSION = 4


_OBSOLETE_TABLE_DROP_ORDER = [
    "task_logs",
    "tasks",
    "accounts",
    "monitor_task_configs",
]


def _utc_now_str() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _ensure_schema_version_table(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    id INTEGER PRIMARY KEY,
                    version INTEGER NOT NULL,
                    updated_at VARCHAR(64) NOT NULL
                )
                """
            )
        )
        existing = conn.execute(
            text("SELECT version FROM schema_version WHERE id = 1")
        ).scalar()
        if existing is None:
            conn.execute(
                text(
                    "INSERT INTO schema_version (id, version, updated_at) VALUES (1, 0, :updated_at)"
                ),
                {"updated_at": _utc_now_str()},
            )


def get_current_schema_version(engine: Engine) -> int:
    _ensure_schema_version_table(engine)
    with engine.connect() as conn:
        version = conn.execute(
            text("SELECT version FROM schema_version WHERE id = 1")
        ).scalar()
    return int(version or 0)


def _set_current_schema_version(conn: Connection, version: int) -> None:
    conn.execute(
        text(
            "UPDATE schema_version SET version = :version, updated_at = :updated_at WHERE id = 1"
        ),
        {"version": version, "updated_at": _utc_now_str()},
    )


def _table_names(conn: Connection) -> set[str]:
    return set(inspect(conn).get_table_names())


def _column_names(conn: Connection, table_name: str) -> set[str]:
    return {col["name"] for col in inspect(conn).get_columns(table_name)}


def _upgrade_to_v1(conn: Connection) -> None:
    tables = _table_names(conn)
    if "account_sessions" not in tables:
        return
    columns = _column_names(conn, "account_sessions")
    if "chat_cache_ttl_minutes" not in columns:
        conn.execute(
            text(
                "ALTER TABLE account_sessions ADD COLUMN chat_cache_ttl_minutes INTEGER NOT NULL DEFAULT 1440"
            )
        )


def _upgrade_to_v2(conn: Connection) -> None:
    tables = _table_names(conn)
    if "sign_task_runs" not in tables:
        return
    columns = _column_names(conn, "sign_task_runs")
    if "flow_items" not in columns:
        conn.execute(
            text("ALTER TABLE sign_task_runs ADD COLUMN flow_items TEXT NULL")
        )


def _rebuild_account_chat_cache_meta_without_legacy_ttl(conn: Connection) -> None:
    tables = _table_names(conn)
    has_items = "account_chat_cache_items" in tables

    conn.execute(
        text(
            """
            CREATE TABLE account_chat_cache_meta_new (
                id INTEGER NOT NULL PRIMARY KEY,
                account_name VARCHAR(100) NOT NULL UNIQUE,
                last_cached_at DATETIME NULL,
                last_refresh_status VARCHAR(32) NULL,
                last_refresh_error TEXT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
    )
    conn.execute(
        text(
            """
            INSERT INTO account_chat_cache_meta_new (
                id,
                account_name,
                last_cached_at,
                last_refresh_status,
                last_refresh_error,
                created_at,
                updated_at
            )
            SELECT
                id,
                account_name,
                last_cached_at,
                last_refresh_status,
                last_refresh_error,
                created_at,
                updated_at
            FROM account_chat_cache_meta
            """
        )
    )

    if has_items:
        conn.execute(
            text(
                """
                CREATE TABLE account_chat_cache_items_new (
                    id INTEGER NOT NULL PRIMARY KEY,
                    account_name VARCHAR(100) NOT NULL,
                    chat_id BIGINT NOT NULL,
                    title VARCHAR(512) NULL,
                    username VARCHAR(255) NULL,
                    chat_type VARCHAR(64) NOT NULL,
                    first_name VARCHAR(255) NULL,
                    cached_at DATETIME NOT NULL,
                    CONSTRAINT uq_account_chat_cache_items_account_chat UNIQUE (account_name, chat_id),
                    FOREIGN KEY(account_name) REFERENCES account_chat_cache_meta_new (account_name) ON DELETE CASCADE
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO account_chat_cache_items_new (
                    id,
                    account_name,
                    chat_id,
                    title,
                    username,
                    chat_type,
                    first_name,
                    cached_at
                )
                SELECT
                    id,
                    account_name,
                    chat_id,
                    title,
                    username,
                    chat_type,
                    first_name,
                    cached_at
                FROM account_chat_cache_items
                """
            )
        )

    if has_items:
        conn.execute(text("DROP TABLE account_chat_cache_items"))
    conn.execute(text("DROP TABLE account_chat_cache_meta"))
    conn.execute(text("ALTER TABLE account_chat_cache_meta_new RENAME TO account_chat_cache_meta"))

    if has_items:
        conn.execute(
            text(
                "ALTER TABLE account_chat_cache_items_new RENAME TO account_chat_cache_items"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_account_chat_cache_items_account_name ON account_chat_cache_items (account_name)"
            )
        )



def _drop_obsolete_tables(conn: Connection) -> None:
    import logging
    from sqlalchemy import quoted_name

    logger = logging.getLogger("backend.schema_migrator")
    tables = _table_names(conn)
    # 白名单验证：仅允许删除预定义的废弃表
    allowed_tables = set(_OBSOLETE_TABLE_DROP_ORDER)

    for table_name in _OBSOLETE_TABLE_DROP_ORDER:
        if table_name not in tables:
            continue

        # 双重检查：确保表名在白名单中
        if table_name not in allowed_tables:
            logger.error(f"拒绝删除非白名单表: {table_name}")
            continue

        logger.info(f"Dropping obsolete table: {table_name}")
        # 使用 SQLAlchemy 的安全引用
        safe_table = quoted_name(table_name, quote=True)
        conn.execute(text(f"DROP TABLE {safe_table}"))



def _drop_legacy_account_chat_cache_meta_ttl(conn: Connection) -> None:
    tables = _table_names(conn)
    if "account_chat_cache_meta" not in tables:
        return

    columns = _column_names(conn, "account_chat_cache_meta")
    if "cache_ttl_minutes" not in columns:
        return

    try:
        conn.execute(
            text(
                "ALTER TABLE account_chat_cache_meta DROP COLUMN cache_ttl_minutes"
            )
        )
    except Exception:
        if conn.dialect.name != "sqlite":
            raise
        _rebuild_account_chat_cache_meta_without_legacy_ttl(conn)



def _upgrade_to_v3(conn: Connection) -> None:
    tables = _table_names(conn)
    if "sign_task_runs" in tables:
        columns = _column_names(conn, "sign_task_runs")
        if "flow_truncated" not in columns:
            conn.execute(
                text(
                    "ALTER TABLE sign_task_runs ADD COLUMN flow_truncated BOOLEAN NOT NULL DEFAULT 0"
                )
            )
        if "flow_line_count" not in columns:
            conn.execute(
                text(
                    "ALTER TABLE sign_task_runs ADD COLUMN flow_line_count INTEGER NOT NULL DEFAULT 0"
                )
            )

    _drop_legacy_account_chat_cache_meta_ttl(conn)
    _drop_obsolete_tables(conn)


def _upgrade_to_v4(conn: Connection) -> None:
    tables = _table_names(conn)
    if "sign_task_configs" not in tables:
        return
    columns = _column_names(conn, "sign_task_configs")
    if "next_scheduled_at" not in columns:
        # PostgreSQL 使用 TIMESTAMP，SQLite 使用 DATETIME
        datetime_type = "TIMESTAMP" if conn.dialect.name == "postgresql" else "DATETIME"
        conn.execute(
            text(
                f"ALTER TABLE sign_task_configs ADD COLUMN next_scheduled_at {datetime_type} NULL"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_sign_task_configs_next_scheduled_at ON sign_task_configs (next_scheduled_at)"
            )
        )


_MIGRATIONS: list[tuple[int, Callable[[Connection], None]]] = [
    (1, _upgrade_to_v1),
    (2, _upgrade_to_v2),
    (3, _upgrade_to_v3),
    (4, _upgrade_to_v4),
]



def upgrade_schema(engine: Engine) -> int:
    _ensure_schema_version_table(engine)
    Base.metadata.create_all(bind=engine)

    with engine.connect() as conn:
        current_version = int(
            conn.execute(text("SELECT version FROM schema_version WHERE id = 1")).scalar() or 0
        )
    if current_version > LATEST_SCHEMA_VERSION:
        raise RuntimeError(
            f"数据库 schema 版本 {current_version} 高于当前代码支持的版本 {LATEST_SCHEMA_VERSION}"
        )

    for target_version, migration in _MIGRATIONS:
        if current_version >= target_version:
            continue
        with engine.begin() as conn:
            migration(conn)
            _set_current_schema_version(conn, target_version)
        current_version = target_version

    return current_version
