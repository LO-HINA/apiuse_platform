"""会话 schema:列表瘦身条目 + 详情/删除/创建响应。"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel

from app.modules.messages.schemas import Message


class SessionCreatedResponse(BaseModel):
    session_id: UUID


class SessionDetailResponse(BaseModel):
    session_id: UUID
    messages: List[Message]


class SessionSummary(BaseModel):
    """列表里的瘦身条目,只含元信息。"""
    id: UUID
    title: Optional[str]
    created_at: datetime
    updated_at: datetime


class SessionListResponse(BaseModel):
    sessions: List[SessionSummary]


class SessionDeleteResponse(BaseModel):
    success: bool
