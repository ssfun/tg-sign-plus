from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from backend.core.database import Base


class AccountChatCacheMeta(Base):
    __tablename__ = "account_chat_cache_meta"

    id = Column(Integer, primary_key=True)
    account_name = Column(String(100), unique=True, nullable=False)
    last_cached_at = Column(DateTime, nullable=True)
    last_refresh_status = Column(String(32), nullable=True)
    last_refresh_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class AccountChatCacheItem(Base):
    __tablename__ = "account_chat_cache_items"
    __table_args__ = (
        UniqueConstraint("account_name", "chat_id", name="uq_account_chat_cache_items_account_chat"),
    )

    id = Column(Integer, primary_key=True)
    account_name = Column(
        String(100),
        ForeignKey("account_chat_cache_meta.account_name", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chat_id = Column(BigInteger, nullable=False)
    title = Column(String(512), nullable=True)
    username = Column(String(255), nullable=True)
    chat_type = Column(String(64), nullable=False)
    first_name = Column(String(255), nullable=True)
    cached_at = Column(DateTime, default=datetime.utcnow, nullable=False)
