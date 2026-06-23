"""adapter 通用工具：httpx 单例 + messages 拼接。

chat 路径用 build_messages 拼 system prompt + history + user message，
adapter 用 get_http_client 拿全局 httpx 客户端。

上游通信逻辑已移入各 ProviderAdapter 实现（openai_compat_adapter.py 等）。
"""

from __future__ import annotations

import logging
from typing import List, Optional, Sequence

import httpx

from app.core.config import settings
from app.modules.messages.schemas import Message

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# httpx.AsyncClient 单例,由 main.py 的 lifespan 注入
# ----------------------------------------------------------------------

_http_client: Optional[httpx.AsyncClient] = None


def set_http_client(client: Optional[httpx.AsyncClient]) -> None:
    global _http_client
    _http_client = client


def get_http_client() -> httpx.AsyncClient:
    if _http_client is None:
        raise RuntimeError(
            "httpx.AsyncClient 还没初始化,确认 main.py 的 lifespan 已执行 set_http_client。"
        )
    return _http_client


# ----------------------------------------------------------------------
# OpenAI 兼容 messages 拼接:system → history → 本轮 user
# ----------------------------------------------------------------------


def build_messages(
    message: str,
    history: Optional[Sequence[Message]],
) -> List[dict]:
    messages: List[dict] = []
    if settings.AI_SYSTEM_PROMPT:
        messages.append({"role": "system", "content": settings.AI_SYSTEM_PROMPT})
    for m in (history or []):
        messages.append({"role": m.role.value, "content": m.content})
    messages.append({"role": "user", "content": message})
    return messages
