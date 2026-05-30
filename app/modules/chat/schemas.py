"""聊天 schema:请求体 + SSE 事件帧。

EventSource 读不到自定义响应头,session_id 必须放进流里作为首帧。
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """非流式聊天请求体(暂未启用,留作兼容)。"""
    session_id: Optional[UUID] = Field(default=None, description="不传则新建")
    message: str = Field(..., min_length=1, max_length=10000)


class ChatResponse(BaseModel):
    session_id: UUID
    reply: str


class HealthResponse(BaseModel):
    status: str
    message: str


# ======================================================================
# SSE 事件:每条都是 ``data: <json>\n\n``
# ======================================================================

class StreamTokenEvent(BaseModel):
    token: str


class StreamErrorEvent(BaseModel):
    error: str


class StreamSessionEvent(BaseModel):
    session_id: UUID
