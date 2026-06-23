"""聊天业务编排：sessions/messages CRUD + relay 管道。

chat 是内置客户端——session 管理后委托给 relay+adapter 统一管道，
不再拥有自己的上游调用逻辑。chat 不直接调 adapter。
"""

from __future__ import annotations

import logging
from typing import AsyncIterator, Sequence
from uuid import UUID

from app.core.config import settings
from app.modules.adapter.service import build_messages
from app.modules.channels import crud as channels_crud
from app.modules.messages import crud as messages_crud
from app.modules.messages.schemas import Message, Role
from app.modules.relay import service as relay_service
from app.modules.relay.schemas import ChatCompletionRequest
from app.modules.sessions import service as sessions_service

logger = logging.getLogger(__name__)


def _records_to_schema(rows) -> list[Message]:
    return [
        Message(role=Role(r.role), content=r.content, created_at=r.created_at)
        for r in rows
    ]


async def _take_history(session_id: str) -> list[Message]:
    rows = await messages_crud.list_recent(session_id, limit=settings.SESSION_MAX_MESSAGES)
    return _records_to_schema(rows)


async def _resolve_or_create_session(
    *, session_id: UUID | None, user_id: str | None,
) -> UUID:
    return await sessions_service.resolve_or_create_owned(
        session_id=session_id,
        user_id=user_id,
    )


# ----------------------------------------------------------------------
# 公共
# ----------------------------------------------------------------------


async def _should_use_fake() -> bool:
    """USE_FAKE_AI 为真 或 channel 池为空时走 fake 模式。"""
    if settings.USE_FAKE_AI:
        return True
    return await channels_crud.count() == 0


# ----------------------------------------------------------------------
# 非流式
# ----------------------------------------------------------------------


async def handle_chat(
    *,
    session_id: UUID | None,
    user_message: str,
    user_id: str | None,
    model: str | None = None,
) -> tuple[UUID, str]:
    sid = await _resolve_or_create_session(session_id=session_id, user_id=user_id)
    sid_str = str(sid)

    history = await _take_history(sid_str)
    await messages_crud.add(session_id=sid_str, role=Role.USER.value, content=user_message)

    if await _should_use_fake():
        from app.modules.adapter.fake import fake_ai_reply
        reply = await fake_ai_reply(user_message, history=history, model=model)
    else:
        # 查默认 API Key
        api_key_id: str | None = None
        from app.modules.api_keys.service import get_default_key
        default_key_obj = await get_default_key(user_id)
        if default_key_obj:
            api_key_id = default_key_obj.id

        request = ChatCompletionRequest(
            model=model or settings.AI_MODEL,
            messages=[
                {"role": m["role"], "content": m["content"]}
                for m in build_messages(user_message, history)
            ],
            stream=False,
        )
        response = await relay_service.execute_non_stream(request, api_key_id=api_key_id)
        reply = (response.choices[0].message.content if response.choices else "")

    await messages_crud.add(session_id=sid_str, role=Role.ASSISTANT.value, content=reply)
    await sessions_service.touch(sid)
    await messages_crud.trim_history(sid_str, settings.SESSION_MAX_MESSAGES)
    await sessions_service.cleanup_inactive_message_bodies()

    logger.info(
        "handle_chat done: session_id=%s history=%d reply_len=%d",
        sid, len(history), len(reply),
    )
    return sid, reply


# ----------------------------------------------------------------------
# 流式: 开场 + 收尾
# ----------------------------------------------------------------------


async def prepare_stream(
    *,
    session_id: UUID | None,
    user_message: str,
    user_id: str | None,
) -> tuple[UUID, list[Message]]:
    sid = await _resolve_or_create_session(session_id=session_id, user_id=user_id)
    sid_str = str(sid)

    history = await _take_history(sid_str)
    await messages_crud.add(session_id=sid_str, role=Role.USER.value, content=user_message)
    await sessions_service.touch(sid)
    return sid, history


async def persist_assistant(*, session_id: UUID, content: str) -> int | None:
    if not content:
        logger.info("persist_assistant skipped: session_id=%s empty content", session_id)
        return None

    sid_str = str(session_id)
    msg = await messages_crud.add(
        session_id=sid_str, role=Role.ASSISTANT.value, content=content,
    )
    await sessions_service.touch(session_id)
    await messages_crud.trim_history(sid_str, settings.SESSION_MAX_MESSAGES)
    await sessions_service.cleanup_inactive_message_bodies()
    return msg.id


async def stream_tokens(
    *, user_message: str, history: Sequence[Message], model: str | None = None,
    user_id: str | None = None,
) -> AsyncIterator[str]:
    """从 relay.execute_stream 取 ChatCompletionChunk，提取 token 文本。

    ChannelPoolError 时若 USE_FAKE_AI 为真则回退 fake 模式。
    """
    if await _should_use_fake():
        from app.modules.adapter.fake import fake_ai_stream
        async for token in fake_ai_stream(user_message, history=history, model=model):
            yield token
        return

    api_key_id: str | None = None
    if user_id:
        from app.modules.api_keys.service import get_default_key
        default_key = await get_default_key(user_id)
        if default_key:
            api_key_id = default_key.id

    request = ChatCompletionRequest(
        model=model or settings.AI_MODEL,
        messages=[
            {"role": m["role"], "content": m["content"]}
            for m in build_messages(user_message, history)
        ],
        stream=True,
    )
    try:
        async for chunk in relay_service.execute_stream(request, api_key_id=api_key_id):
            if chunk.choices:
                content = chunk.choices[0].delta.content
                if content:
                    yield content
    except relay_service.channels_service.ChannelPoolError:
        if settings.USE_FAKE_AI:
            logger.warning("channel pool exhausted, falling back to fake AI")
            from app.modules.adapter.fake import fake_ai_stream
            async for token in fake_ai_stream(user_message, history=history, model=model):
                yield token
        else:
            raise


# ----------------------------------------------------------------------
# 文件尾
# ----------------------------------------------------------------------
