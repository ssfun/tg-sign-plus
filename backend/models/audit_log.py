"""审计日志模型

记录用户的关键操作，用于安全审计和问题追踪。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, Text

from backend.core.database import Base


class AuditLog(Base):
    """审计日志表"""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=True, index=True)  # 用户 ID，可为空（如登录失败）
    username = Column(String(64), nullable=True)  # 用户名快照
    action = Column(String(64), nullable=False, index=True)  # 操作类型
    resource_type = Column(String(64), nullable=True)  # 资源类型
    resource_id = Column(String(128), nullable=True)  # 资源 ID
    ip_address = Column(String(45), nullable=True)  # IPv4/IPv6 地址
    user_agent = Column(String(512), nullable=True)  # User-Agent
    details = Column(Text, nullable=True)  # 详细信息（JSON）
    status = Column(String(20), nullable=False, default="success")  # success/failure
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<AuditLog(id={self.id}, action={self.action}, user={self.username})>"
