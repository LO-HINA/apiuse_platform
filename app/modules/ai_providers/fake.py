"""fake AI:离线可用,刻意写成"明显是 fake"以避免误以为接通真模型。"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator, Optional, Sequence

from app.modules.messages.schemas import Message

logger = logging.getLogger(__name__)


_FAKE_REPLY = (
    "[FAKE 模式] 当前未连接真实模型。"
    "在 .env 里设 USE_FAKE_AI=false,并在 data/channels.json 配好 channel 即可切换。"
)


async def fake_ai_reply(
    message: str, history: Optional[Sequence[Message]] = None,
) -> str:
    logger.debug(
        "fake_ai_reply: msg_len=%d history_len=%d",
        len(message), len(history or []),
    )
    await asyncio.sleep(0.3)
    return _FAKE_REPLY


async def fake_ai_stream(
    message: str, history: Optional[Sequence[Message]] = None,
) -> AsyncGenerator[str, None]:
    logger.debug(
        "fake_ai_stream start: msg_len=%d history_len=%d",
        len(message), len(history or []),
    )
    for char in _FAKE_REPLY:
        await asyncio.sleep(0.05)
        yield char
