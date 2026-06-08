"""Channel 领域 schema。

M2 的 channel 是"上游账号 / key / base_url / 模型列表"的最小单位。
api_key 仍然是普通字符串字段,因为它需要原样写入本机 `data/channels.json`;
安全边界靠 `.gitignore`、不对外返回、不写日志来保证。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChannelConfig(BaseModel):
    """JSON 文件中的一条 channel 记录,同时保存少量运行时状态。"""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=120)
    provider_type: Literal["openai_compat"] = "openai_compat"
    base_url: str = Field(..., min_length=1, max_length=500)
    api_key: str = Field(..., min_length=1, repr=False)
    models: list[str] = Field(default_factory=list)
    weight: int = Field(default=1, ge=1, le=1000)
    enabled: bool = True

    # 运行时字段。M2 直接持久化到 channels.json,便于本地重启后保留短期故障状态。
    blacklisted_until: datetime | None = None
    success_count: int = Field(default=0, ge=0)
    failure_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("base_url")
    @classmethod
    def _normalize_base_url(cls, value: str) -> str:
        """统一去掉尾部 `/`,避免后续拼路径出现 `//chat/completions`。"""
        normalized = value.strip().rstrip("/")
        if not normalized:
            raise ValueError("base_url cannot be empty")
        return normalized

    @field_validator("models")
    @classmethod
    def _normalize_models(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]

    @field_validator("blacklisted_until", "created_at", "updated_at")
    @classmethod
    def _ensure_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    def model_for_request(self, fallback: str) -> str:
        """选择本次请求使用的模型。

        优先使用 channel 自己的第一个模型;没有配置 models 时才回落到全局 AI_MODEL。
        这样 M2 可以用每个 channel 的模型列表做最小调度,不需要先做 M3 管理界面。
        """
        if self.models:
            return self.models[0]
        return fallback

    def safe_label(self) -> str:
        """日志里只用 id/name 定位 channel,绝不拼 api_key。"""
        return f"{self.id}({self.name})"


class ChannelFailureSnapshot(BaseModel):
    """全军覆没时给日志看的安全摘要。"""

    channel_id: str
    name: str
    reason: str
    retryable: bool
