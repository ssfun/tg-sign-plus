"""时区工具模块

提供统一的时区处理函数，确保所有时间戳使用 UTC 时区。
"""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """返回 UTC 时间（timezone-aware）

    推荐在新代码中使用此函数，返回带时区信息的 datetime 对象。

    Returns:
        带 UTC 时区信息的 datetime 对象
    """
    return datetime.now(timezone.utc)


def utcnow_naive() -> datetime:
    """返回 UTC 时间（naive，不带时区信息）

    用于兼容旧代码和数据库操作，返回不带时区信息的 datetime 对象。
    注意：此函数仅用于向后兼容，新代码应使用 utcnow()。

    Returns:
        不带时区信息的 UTC datetime 对象
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc(dt: datetime) -> datetime:
    """将任意时区的 datetime 转换为 UTC

    Args:
        dt: 输入的 datetime 对象（可以是 naive 或 aware）

    Returns:
        UTC 时区的 datetime 对象
    """
    if dt.tzinfo is None:
        # 如果是 naive datetime，假设它已经是 UTC
        return dt.replace(tzinfo=timezone.utc)
    else:
        # 如果是 aware datetime，转换到 UTC
        return dt.astimezone(timezone.utc)


def from_timestamp(timestamp: float) -> datetime:
    """从 Unix 时间戳创建 UTC datetime

    Args:
        timestamp: Unix 时间戳（秒）

    Returns:
        UTC 时区的 datetime 对象
    """
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)
