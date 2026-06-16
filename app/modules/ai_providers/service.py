"""AI 调度入口 + httpx 单例 + messages 拼接。

按 USE_FAKE_AI 选 fake / openai_compat 实现。M2 起 real_* 内部不再读
settings.AI_*,改为按 channel 拿 base_url / api_key。
"""
from __future__ import annotations

import logging
from typing import AsyncGenerator, List, Optional, Sequence

import httpx

from app.core.config import settings
from app.modules.channels import crud as channels_crud
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


# ----------------------------------------------------------------------
# 统一入口
# ----------------------------------------------------------------------

async def dispatch_chat(
    message: str, history: Optional[Sequence[Message]] = None,
) -> str:
    from app.modules.ai_providers import fake, openai_compat

    if not settings.USE_FAKE_AI and channels_crud.count() == 0:
        logger.warning("channel pool empty, falling back to fake AI")
        return await fake.fake_ai_reply(message, history=history)

    impl = fake.fake_ai_reply if settings.USE_FAKE_AI else openai_compat.real_ai_reply
    return await impl(message, history=history)


async def dispatch_chat_stream(
    message: str, history: Optional[Sequence[Message]] = None,
) -> AsyncGenerator[str, None]:
    """命名 dispatch_* 避免和路由 handler 撞名。"""
    from app.modules.ai_providers import fake, openai_compat

    if not settings.USE_FAKE_AI and channels_crud.count() == 0:
        logger.warning("channel pool empty, falling back to fake AI")
        impl = fake.fake_ai_stream
    else:
        impl = fake.fake_ai_stream if settings.USE_FAKE_AI else openai_compat.real_ai_stream
    async for token in impl(message, history=history):
        yield token
