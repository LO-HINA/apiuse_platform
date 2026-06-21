"""Schemas for channel pool management."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class ChannelConfig(BaseModel):
    """Local channel record stored in SQLite database."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=120)
    provider_type: Literal["openai_compat"] = "openai_compat"
    base_url: str = Field(..., min_length=1, max_length=500)
    api_key: str = Field(..., min_length=1, repr=False)
    organization: str | None = Field(default=None, max_length=120)
    models: list[str] = Field(default_factory=list)
    group: str = Field(default="default", min_length=1, max_length=80)
    model_redirect: dict[str, str] = Field(default_factory=dict)
    weight: int = Field(default=1, ge=1, le=1000)
    enabled: bool = True
    blacklisted_until: datetime | None = None
    success_count: int = Field(default=0, ge=0)
    failure_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("base_url")
    @classmethod
    def _normalize_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized:
            raise ValueError("base_url cannot be empty")
        return normalized

    @field_validator("models")
    @classmethod
    def _normalize_models(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]

    @field_validator("model_redirect")
    @classmethod
    def _normalize_model_redirect(cls, value: dict[str, str]) -> dict[str, str]:
        return {
            key.strip(): target.strip()
            for key, target in value.items()
            if key.strip() and target.strip()
        }

    @field_validator("blacklisted_until", "created_at", "updated_at")
    @classmethod
    def _ensure_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    def model_for_request(self, fallback: str) -> str:
        if self.models:
            return self.models[0]
        return fallback

    def safe_label(self) -> str:
        return f"{self.id}({self.name})"


class ChannelCreateRequest(BaseModel):
    """Admin request for creating one channel."""

    id: str | None = Field(default=None, min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=120)
    provider_type: Literal["openai_compat"] = "openai_compat"
    base_url: str | None = Field(default=None, max_length=500)
    api_key: SecretStr = Field(..., min_length=1)
    organization: str | None = Field(default=None, max_length=120)
    models: list[str] = Field(..., min_length=1)
    custom_model_name: str | None = Field(default=None, max_length=160)
    group: str = Field(default="default", min_length=1, max_length=80)
    model_redirect: dict[str, str] = Field(default_factory=dict)
    weight: int = Field(default=1, ge=1, le=1000)
    enabled: bool = True

    @field_validator("base_url")
    @classmethod
    def _normalize_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().rstrip("/")
        if not normalized:
            return None
        return normalized

    @field_validator("models")
    @classmethod
    def _normalize_models(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]

    @field_validator("model_redirect")
    @classmethod
    def _normalize_model_redirect(cls, value: dict[str, str]) -> dict[str, str]:
        return {
            key.strip(): target.strip()
            for key, target in value.items()
            if key.strip() and target.strip()
        }


class ChannelPublic(BaseModel):
    """Browser-safe channel response."""

    id: str
    name: str
    provider_type: Literal["openai_compat"]
    base_url: str
    api_key_masked: str
    organization: str | None
    models: list[str]
    group: str
    model_redirect: dict[str, str]
    weight: int
    enabled: bool
    blacklisted_until: datetime | None
    success_count: int
    failure_count: int
    created_at: datetime
    updated_at: datetime


class ChannelBulkImportRequest(BaseModel):
    """Raw bulk import text."""

    raw_text: str = Field(..., min_length=1, max_length=20000)


class ChannelBulkImportResponse(BaseModel):
    imported: int
    skipped: int
    errors: list[str] = Field(default_factory=list)
    channels: list[ChannelPublic] = Field(default_factory=list)


class ChannelModelOptionsResponse(BaseModel):
    provider_type: Literal["openai_compat"] = "openai_compat"
    models: list[str]


class ChannelFailureSnapshot(BaseModel):
    """Safe failure summary."""

    channel_id: str
    name: str
    reason: str
    retryable: bool
