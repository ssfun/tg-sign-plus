from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from backend.core.database import Base


class AccountSession(Base):
    __tablename__ = "account_sessions"

    id = Column(Integer, primary_key=True)
    account_name = Column(String(100), unique=True, nullable=False)
    session_string = Column(Text, nullable=True)
    remark = Column(String(255), nullable=True)
    proxy = Column(Text, nullable=True)
    chat_cache_ttl_minutes = Column(Integer, nullable=False, default=1440)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
