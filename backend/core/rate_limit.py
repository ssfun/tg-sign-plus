"""速率限制模块

提供基于 slowapi 的速率限制功能，防止暴力破解和 API 滥用。
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address


# 创建全局 limiter 实例
limiter = Limiter(key_func=get_remote_address)


def get_limiter() -> Limiter:
    """获取 limiter 实例

    Returns:
        Limiter 实例
    """
    return limiter
