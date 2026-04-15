from __future__ import annotations

import logging
import os

from sqlalchemy.orm import Session

from backend.core.security import hash_password
from backend.models.user import User

logger = logging.getLogger("backend.users")


def ensure_admin(db: Session, username: str = "admin", password: str = None):
    """
    仅在用户表为空时创建一个默认管理员。
    防止用户修改用户名后，系统又自动创建一个默认的 admin 账号。
    """
    from backend.core.validators import validate_password_strength, ValidationError

    # 检查是否已有任何用户存在
    first_user = db.query(User).first()
    if first_user:
        return first_user

    if not password:
        env_pwd = os.getenv("ADMIN_PASSWORD")
        if env_pwd:
            password = env_pwd
            # 验证环境变量中的密码强度
            try:
                validate_password_strength(password)
            except ValidationError as e:
                logger.error(f"ADMIN_PASSWORD 不符合密码强度要求: {e}")
                raise RuntimeError(f"ADMIN_PASSWORD 不符合密码强度要求: {e}")
        else:
            # 默认密码不符合强度要求，生成一个强密码
            import secrets
            import string
            # 生成包含大小写字母和数字的 16 位随机密码
            alphabet = string.ascii_letters + string.digits
            password = ''.join(secrets.choice(alphabet) for _ in range(16))
            # 确保包含大写、小写和数字
            password = 'Admin' + password[5:] + '123'
            logger.warning(
                f"SECURITY WARNING: Default admin account created with random password: '{password}'. "
                "Please save this password and change it immediately, or set ADMIN_PASSWORD environment variable."
            )

    # 如果没有任何用户，则创建默认管理员
    new_user = User(username=username, password_hash=hash_password(password))
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user
