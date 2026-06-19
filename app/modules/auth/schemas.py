"""鉴权 schema:请求体走 SecretStr 防日志泄漏,响应体严格不含 password_hash。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class AuthStatusResponse(BaseModel):
    """公开状态:系统是否有用户。"""
    has_users: bool


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: SecretStr = Field(..., min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=64)


class LoginRequest(BaseModel):
    """长度上限放宽,避免老用户撞新规则登不上。"""
    username: str = Field(..., min_length=1, max_length=64)
    password: SecretStr = Field(..., min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="距离过期还剩多少秒")


class UserResponse(BaseModel):
    """对外暴露的用户信息,严格不含 password_hash。"""
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    display_name: str | None
    role: str = "user"
    status: str
    created_at: datetime
