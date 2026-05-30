"""OpenAI 兼容协议实现:POST /chat/completions,流式 / 非流式两路。

M2 起会被号池调度替换 —— 不再直接读 settings.AI_*,而是接受 channel 参数。
"""
from __future__ import annotations

import json
import logging
from typing import AsyncGenerator, Optional, Sequence

from app.core.config import settings
from app.modules.ai_providers.service import build_messages, get_http_client
from app.modules.messages.schemas import Message

logger = logging.getLogger(__name__)


async def real_ai_stream(
    message: str, history: Optional[Sequence[Message]] = None,
) -> AsyncGenerator[str, None]:
    """stream=true 逐行解析 SSE,只透传 delta.content。"""
    client = get_http_client()
    url = f"{settings.AI_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.AI_API_KEY.get_secret_value()}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.AI_MODEL,
        "messages": build_messages(message, history),
        "stream": True,
    }

    logger.info("real_ai_stream calling: url=%s model=%s", url, settings.AI_MODEL)

    async with client.stream(
        "POST", url, json=payload, headers=headers, timeout=settings.REQUEST_TIMEOUT,
    ) as resp:
        resp.raise_for_status()

        async for line in resp.aiter_lines():
            if not line or not line.startswith("data: "):
                continue
            data = line[len("data: "):].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                logger.warning("upstream non-json line: %s", data[:80])
                continue

            choices = chunk.get("choices") or []
            if not choices:
                continue
            token = (choices[0].get("delta") or {}).get("content")
            if token:
                yield token

    logger.info("real_ai_stream done")


async def real_ai_reply(
    message: str, history: Optional[Sequence[Message]] = None,
) -> str:
    """非流式版,一次性拿完整 JSON。"""
    client = get_http_client()
    url = f"{settings.AI_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.AI_API_KEY.get_secret_value()}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.AI_MODEL,
        "messages": build_messages(message, history),
        "stream": False,
    }

    logger.info("real_ai_reply calling: url=%s model=%s", url, settings.AI_MODEL)

    resp = await client.post(url, json=payload, headers=headers, timeout=settings.REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("upstream returned no choices")
    return (choices[0].get("message") or {}).get("content") or ""
