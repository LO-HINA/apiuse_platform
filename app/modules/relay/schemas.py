"""OpenAI-compatible request / response Pydantic models.

Aligns with https://platform.openai.com/docs/api-reference/chat/create
so external clients using the OpenAI SDK can call this endpoint directly.
"""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "function", "tool"] = "user"
    content: str | list[dict] = ""
    name: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str = Field(..., min_length=1, max_length=160)
    messages: list[ChatMessage] = Field(..., min_length=1)
    stream: bool = False
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    frequency_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    presence_penalty: float | None = Field(default=None, ge=-2.0, le=2.0)
    stop: str | list[str] | None = None


# ---------------------------------------------------------------------------
# Response (non-streaming)
# ---------------------------------------------------------------------------


class ChatMessageResponse(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class ChatChoice(BaseModel):
    index: int = 0
    message: ChatMessageResponse
    finish_reason: Literal["stop", "length", "content_filter", "tool_calls"] | None = "stop"


class ChatUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[ChatChoice]
    usage: ChatUsage | None = None


# ---------------------------------------------------------------------------
# Streaming chunk
# ---------------------------------------------------------------------------


class ChatDelta(BaseModel):
    role: Literal["assistant"] | None = None
    content: str | None = None


class ChatChunkChoice(BaseModel):
    index: int = 0
    delta: ChatDelta = Field(default_factory=ChatDelta)
    finish_reason: Literal["stop", "length", "content_filter", "tool_calls"] | None = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChatChunkChoice] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _completion_id(prefix: str = "chatcmpl") -> str:
    import secrets
    return f"{prefix}-{secrets.token_hex(14)}"


def _now_ts() -> int:
    return int(time.time())
