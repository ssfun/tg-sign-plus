from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint

from backend.core.database import Base


class SignTaskConfig(Base):
    __tablename__ = "sign_task_configs"
    __table_args__ = (
        UniqueConstraint("account_name", "task_name", name="uq_account_task"),
    )

    id = Column(Integer, primary_key=True)
    account_name = Column(String(100), nullable=False, index=True)
    task_name = Column(String(100), nullable=False, index=True)
    config_json = Column(Text, nullable=False)  # JSON string, JSONB on Postgres
    enabled = Column(Boolean, default=True, nullable=False)
    sign_at = Column(String(64), nullable=True)
    next_scheduled_at = Column(DateTime, nullable=True, index=True)  # 预计执行时间
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
