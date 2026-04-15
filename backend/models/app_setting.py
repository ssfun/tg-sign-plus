from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text

from backend.core.database import Base


class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String(100), primary_key=True)
    value_json = Column(Text, nullable=True)  # JSON string
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
