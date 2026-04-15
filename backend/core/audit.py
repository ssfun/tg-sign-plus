"""审计日志装饰器和工具函数

提供便捷的审计日志记录功能。
"""

from __future__ import annotations

import json
import logging
from functools import wraps
from typing import Optional, Any, Callable

from fastapi import Request
from sqlalchemy.orm import Session

from backend.models.audit_log import AuditLog
from backend.models.user import User


logger = logging.getLogger("backend.audit")


def get_client_ip(request: Request) -> str:
    """获取客户端 IP 地址

    Args:
        request: FastAPI Request 对象

    Returns:
        客户端 IP 地址
    """
    # 优先从 X-Forwarded-For 获取（代理/负载均衡场景）
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()

    # 其次从 X-Real-IP 获取
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    # 最后使用直连 IP
    if request.client:
        return request.client.host

    return "unknown"


def log_audit(
    db: Session,
    action: str,
    user: Optional[User] = None,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    details: Optional[dict] = None,
    status: str = "success",
) -> AuditLog:
    """记录审计日志

    Args:
        db: 数据库会话
        action: 操作类型（如 "login", "logout", "password_change"）
        user: 用户对象
        user_id: 用户 ID（如果没有 user 对象）
        username: 用户名（如果没有 user 对象）
        resource_type: 资源类型（如 "account", "task"）
        resource_id: 资源 ID
        ip_address: 客户端 IP
        user_agent: User-Agent
        details: 详细信息字典
        status: 操作状态（success/failure）

    Returns:
        创建的审计日志对象
    """
    if user:
        user_id = user.id
        username = user.username

    audit_log = AuditLog(
        user_id=user_id,
        username=username,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip_address,
        user_agent=user_agent,
        details=json.dumps(details, ensure_ascii=False) if details else None,
        status=status,
    )

    try:
        db.add(audit_log)
        db.commit()
        db.refresh(audit_log)
        logger.info(
            f"审计日志: {action} by {username or 'anonymous'} "
            f"({status}) - {resource_type}:{resource_id}"
        )
    except Exception as e:
        logger.error(f"记录审计日志失败: {e}", exc_info=True)
        db.rollback()

    return audit_log


def audit_action(
    action: str,
    resource_type: Optional[str] = None,
    get_resource_id: Optional[Callable[[Any], str]] = None,
):
    """审计日志装饰器

    用于自动记录 API 路由的操作日志。

    Args:
        action: 操作类型
        resource_type: 资源类型
        get_resource_id: 从函数参数中提取资源 ID 的函数

    Example:
        @router.delete("/accounts/{account_name}")
        @audit_action("account_delete", resource_type="account",
                      get_resource_id=lambda kwargs: kwargs.get("account_name"))
        def delete_account(account_name: str, ...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # 提取参数
            request: Optional[Request] = kwargs.get("request")
            db: Optional[Session] = kwargs.get("db")
            current_user: Optional[User] = kwargs.get("current_user")

            resource_id = None
            if get_resource_id:
                try:
                    resource_id = get_resource_id(kwargs)
                except Exception as e:
                    logger.warning(f"提取资源 ID 失败: {e}")

            # 执行原函数
            status = "success"
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                status = "failure"
                raise
            finally:
                # 记录审计日志
                if db and request:
                    try:
                        log_audit(
                            db=db,
                            action=action,
                            user=current_user,
                            resource_type=resource_type,
                            resource_id=resource_id,
                            ip_address=get_client_ip(request),
                            user_agent=request.headers.get("User-Agent"),
                            status=status,
                        )
                    except Exception as log_error:
                        logger.error(f"审计日志记录失败: {log_error}")

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # 提取参数
            request: Optional[Request] = kwargs.get("request")
            db: Optional[Session] = kwargs.get("db")
            current_user: Optional[User] = kwargs.get("current_user")

            resource_id = None
            if get_resource_id:
                try:
                    resource_id = get_resource_id(kwargs)
                except Exception as e:
                    logger.warning(f"提取资源 ID 失败: {e}")

            # 执行原函数
            status = "success"
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                status = "failure"
                raise
            finally:
                # 记录审计日志
                if db and request:
                    try:
                        log_audit(
                            db=db,
                            action=action,
                            user=current_user,
                            resource_type=resource_type,
                            resource_id=resource_id,
                            ip_address=get_client_ip(request),
                            user_agent=request.headers.get("User-Agent"),
                            status=status,
                        )
                    except Exception as log_error:
                        logger.error(f"审计日志记录失败: {log_error}")

        # 根据原函数是否为协程选择包装器
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator
