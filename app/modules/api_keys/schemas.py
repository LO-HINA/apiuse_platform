from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., min_length=1, max_length=80)
    key_hash: str = Field(..., min_length=1, repr=False)
    key_prefix: str = Field(default="sk-", max_length=10)
    key_masked: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=120)
    models: list[str] = Field(default_factory=list)
    quota: int = Field(default=0, ge=0)
    used_quota: int = Field(default=0, ge=0)
    status: Literal["active", "disabled"] = "active"
    user_id: str = Field(..., min_length=1, max_length=80)
    key_encrypted: str | None = None
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    models: list[str] = Field(default_factory=list)
    quota: int = Field(default=0, ge=0)
    validity_days: int | None = Field(default=None, ge=1)
    status: Literal["active", "disabled"] = "active"


class ApiKeyUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    models: list[str] | None = Field(default=None)
    quota: int | None = Field(default=None, ge=0)
    validity_days: int | None = Field(default=None, ge=1)
    status: Literal["active", "disabled"] | None = None


class ApiKeyPublic(BaseModel):
    id: str
    key_masked: str
    name: str
    models: list[str]
    quota: int
    used_quota: int
    status: Literal["active", "disabled"]
    user_id: str
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ApiKeyRevealResponse(BaseModel):
    key: str


class ApiKeyCreateResponse(BaseModel):
    key: str
    key_info: ApiKeyPublic
