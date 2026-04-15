"""统一异常处理模块

提供统一的异常处理函数，记录详细日志但返回通用错误信息，防止敏感信息泄露。
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, status


logger = logging.getLogger("backend.exceptions")


def handle_service_error(
    exc: Exception,
    user_message: str = "操作失败，请稍后重试",
    log_context: Optional[dict] = None,
) -> HTTPException:
    """统一处理服务层异常，记录详细日志但返回通用错误

    Args:
        exc: 原始异常
        user_message: 返回给用户的通用错误信息
        log_context: 额外的日志上下文信息

    Returns:
        HTTPException 实例
    """
    logger.error(
        f"{user_message}: {type(exc).__name__}: {exc}",
        extra=log_context or {},
        exc_info=True,
    )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=user_message,
    )


def handle_not_found(
    resource_type: str,
    resource_id: str,
) -> HTTPException:
    """处理资源不存在的情况

    Args:
        resource_type: 资源类型（如 "账号"、"任务"）
        resource_id: 资源标识

    Returns:
        HTTPException 实例
    """
    logger.warning(f"{resource_type}不存在: {resource_id}")
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"{resource_type}不存在",
    )


def handle_conflict(
    message: str,
    log_context: Optional[dict] = None,
) -> HTTPException:
    """处理资源冲突的情况

    Args:
        message: 冲突描述
        log_context: 额外的日志上下文信息

    Returns:
        HTTPException 实例
    """
    logger.warning(f"资源冲突: {message}", extra=log_context or {})
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=message,
    )


def handle_validation_error(
    message: str,
) -> HTTPException:
    """处理输入验证错误

    Args:
        message: 验证错误描述

    Returns:
        HTTPException 实例
    """
    logger.info(f"输入验证失败: {message}")
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=message,
    )
