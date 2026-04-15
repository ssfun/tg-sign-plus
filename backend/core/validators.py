"""输入验证模块

提供安全的输入验证函数，防止命令注入、路径遍历等安全问题。
"""

from __future__ import annotations

import re

from backend.core.constants import PASSWORD_MIN_LENGTH


# 账号名模式：仅允许字母、数字、下划线、连字符，长度 1-64
ACCOUNT_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')

# 任务名模式：仅允许字母、数字、下划线、连字符，长度 1-128
TASK_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{1,128}$')


class ValidationError(ValueError):
    """验证错误异常"""
    pass


def validate_account_name(name: str) -> str:
    """验证账号名称

    Args:
        name: 账号名称

    Returns:
        验证通过的账号名称

    Raises:
        ValidationError: 验证失败
    """
    if not name or not isinstance(name, str):
        raise ValidationError("账号名不能为空")

    if not ACCOUNT_NAME_PATTERN.match(name):
        raise ValidationError(
            "账号名只能包含字母、数字、下划线和连字符，长度 1-64"
        )

    return name


def validate_task_name(name: str) -> str:
    """验证任务名称

    Args:
        name: 任务名称

    Returns:
        验证通过的任务名称

    Raises:
        ValidationError: 验证失败
    """
    if not name or not isinstance(name, str):
        raise ValidationError("任务名不能为空")

    if not TASK_NAME_PATTERN.match(name):
        raise ValidationError(
            "任务名只能包含字母、数字、下划线和连字符，长度 1-128"
        )

    return name


def validate_password_strength(password: str) -> str:
    """验证密码强度

    要求：
    - 至少 8 位
    - 包含小写字母
    - 包含大写字母
    - 包含数字

    Args:
        password: 密码

    Returns:
        验证通过的密码

    Raises:
        ValidationError: 验证失败
    """
    if not password or not isinstance(password, str):
        raise ValidationError("密码不能为空")

    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValidationError(f"密码长度至少 {PASSWORD_MIN_LENGTH} 位")

    if not re.search(r'[a-z]', password):
        raise ValidationError("密码必须包含小写字母")

    if not re.search(r'[A-Z]', password):
        raise ValidationError("密码必须包含大写字母")

    if not re.search(r'\d', password):
        raise ValidationError("密码必须包含数字")

    return password


def validate_username(username: str) -> str:
    """验证用户名

    Args:
        username: 用户名

    Returns:
        验证通过的用户名

    Raises:
        ValidationError: 验证失败
    """
    if not username or not isinstance(username, str):
        raise ValidationError("用户名不能为空")

    # 用户名使用与账号名相同的规则
    if not ACCOUNT_NAME_PATTERN.match(username):
        raise ValidationError(
            "用户名只能包含字母、数字、下划线和连字符，长度 1-64"
        )

    return username
