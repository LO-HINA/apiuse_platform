"""聊天业务编排:把 sessions/messages crud + ai_providers 组合成业务用例。

路由层只调 service,不直接碰 storage / ai_providers。
内存版下无事务概念,所有写操作幂等且立即生效。
"""
from __future__ import annotations

import logging
from typing import AsyncIterator, Sequence
from uuid import UUID

from app.core.config import settings
from app.modules.ai_providers.service import dispatch_chat, dispatch_chat_stream
from app.modules.messages import crud as messages_crud
from app.modules.messages.schemas import Message, Role
from app.modules.sessions import crud as sessions_crud

logger = logging.getLogger(__name__)


def _records_to_schema(rows) -> list[Message]:
    """MessageRecord → schemas.Message,Role(...) 兜住非法 role。"""
    return [
        Message(role=Role(r.role), content=r.content, created_at=r.created_at)
        for r in rows
    ]


async def _take_history(session_id: str) -> list[Message]:
    """SESSION_MAX_MESSAGES 控制窗口大小。"""
    rows = await messages_crud.list_recent(session_id, limit=settings.SESSION_MAX_MESSAGES)
    return _records_to_schema(rows)


async def _resolve_or_create_session(
    *, session_id: UUID | None, user_id: str | None,
) -> UUID:
    """None → 新建。给了找不到 / 不归你 → LookupError(路由翻 404 防枚举)。"""
    if session_id is None:
        rec = await sessions_crud.create(user_id=user_id)
        return UUID(rec.id)

    sid = str(session_id)
    rec = await sessions_crud.get(sid)
    if rec is None or rec.user_id != user_id:
        raise LookupError("session not found")
    return session_id


# ----------------------------------------------------------------------
# 非流式
# ----------------------------------------------------------------------

async def handle_chat(
    *,
    session_id: UUID | None,
    user_message: str,
    user_id: str | None,
) -> tuple[UUID, str]:
    """resolve session → 写 user → 调 AI → 写 assistant → trim。"""
    sid = await _resolve_or_create_session(session_id=session_id, user_id=user_id)
    sid_str = str(sid)

    history = await _take_history(sid_str)
    await messages_crud.add(session_id=sid_str, role=Role.USER.value, content=user_message)

    reply = await dispatch_chat(user_message, history=history)

    await messages_crud.add(session_id=sid_str, role=Role.ASSISTANT.value, content=reply)
    await sessions_crud.touch(sid_str)
    await messages_crud.trim_history(sid_str, settings.SESSION_MAX_MESSAGES)

    logger.info(
        "handle_chat done: session_id=%s history=%d reply_len=%d",
        sid, len(history), len(reply),
    )
    return sid, reply


# ----------------------------------------------------------------------
# 流式:开场 + 收尾两个独立步骤
# ----------------------------------------------------------------------

async def prepare_stream(
    *,
    session_id: UUID | None,
    user_message: str,
    user_id: str | None,
) -> tuple[UUID, list[Message]]:
    """SSE 开场:resolve session + 取历史 + 写 user + touch。"""
    sid = await _resolve_or_create_session(session_id=session_id, user_id=user_id)
    sid_str = str(sid)

    history = await _take_history(sid_str)
    await messages_crud.add(session_id=sid_str, role=Role.USER.value, content=user_message)
    await sessions_crud.touch(sid_str)
    return sid, history


async def persist_assistant(*, session_id: UUID, content: str) -> int | None:
    """SSE 收尾:写 assistant + touch + trim。空回复跳过。"""
    if not content:
        logger.info("persist_assistant skipped: session_id=%s empty content", session_id)
        return None

    sid_str = str(session_id)
    msg = await messages_crud.add(
        session_id=sid_str, role=Role.ASSISTANT.value, content=content,
    )
    await sessions_crud.touch(sid_str)
    await messages_crud.trim_history(sid_str, settings.SESSION_MAX_MESSAGES)
    return msg.id


async def stream_tokens(
    *, user_message: str, history: Sequence[Message],
) -> AsyncIterator[str]:
    """薄包装:暴露 ai_providers.dispatch_chat_stream 给路由层。"""
    async for token in dispatch_chat_stream(user_message, history=history):
        yield token
