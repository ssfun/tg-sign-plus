from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, validator


class AccountBase(BaseModel):
    account_name: str = Field(..., min_length=1, max_length=64)
    api_id: str = Field(..., max_length=50)
    api_hash: str = Field(..., max_length=100)
    proxy: Optional[str] = Field(None, max_length=500)  # JSON string

    @validator("account_name")
    def validate_account_name(cls, v):
        from backend.core.validators import validate_account_name
        return validate_account_name(v)


class AccountCreate(AccountBase):
    pass


class AccountUpdate(BaseModel):
    api_id: Optional[str] = None
    api_hash: Optional[str] = None
    proxy: Optional[str] = None
    status: Optional[str] = None


class AccountLoginVerify(BaseModel):
    code: Optional[str] = None
    password: Optional[str] = None


class AccountOut(AccountBase):
    id: int
    status: str
    last_login_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True
