"""SSE 流式聊天路由。

路由层只管 SSE 帧封装 / HTTP 状态码,业务逻辑在 chat.service。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from app.api.deps import get_authenticated_user
from app.modules.chat import service as chat_service
from app.modules.chat.schemas import (
    StreamErrorEvent,
    StreamSessionEvent,
    StreamTokenEvent,
)
from app.storage import UserRecord

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


def _safe_stream_error(exc: Exception) -> str:
    """把流内异常转成浏览器可见的安全文本。

    provider/channel 层会给安全异常挂 safe_message;其他异常只返回通用提示。
    原始异常仍由 logger.exception 记录在服务端,避免把上游 URL、响应体、
    Authorization 相关信息或内部类型名直接发给浏览器。
    """
    safe_message = getattr(exc, "safe_message", None)
    if isinstance(safe_message, str) and safe_message:
        return safe_message
    return "流式响应失败,请稍后重试"


@router.get("/chat/stream")
async def chat_stream(
    request: Request,
    current_user: Annotated[UserRecord, Depends(get_authenticated_user)],
    message: str = Query(..., min_length=1, max_length=10000, description="用户输入"),
    session_id: Optional[UUID] = Query(
        None, description="会话 ID,不传则新建;传了但不存在或不归你时返回 404",
    ),
    model: Optional[str] = Query(None, max_length=160, description="指定模型名，不传则使用默认"),
):
    """SSE 流式聊天。

    协议:
        data: {"session_id": "..."}\\n\\n  —— 第一帧
        data: {"token": "..."}\\n\\n       —— 单段 token
        data: {"error": "..."}\\n\\n       —— 流内错误
        data: [DONE]\\n\\n                 —— 结束
    """
    user_id = current_user.id
    try:
        current_session_id, history = await chat_service.prepare_stream(
            session_id=session_id,
            user_message=message,
            user_id=user_id,
        )
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="session not found",
        )

    logger.info(
        "stream chat start: session_id=%s user_id=%s msg_len=%d history=%d model=%s",
        current_session_id, user_id, len(message), len(history), model,
    )

    async def event_generator():
        full_reply = ""
        cancelled = False

        # 第一帧把 session_id 显式发出去:EventSource 拿不到自定义响应头
        first_event = StreamSessionEvent(session_id=current_session_id).model_dump_json()
        yield f"data: {first_event}\n\n"

        try:
            async for token in chat_service.stream_tokens(
                user_message=message, history=history, model=model,
            ):
                if await request.is_disconnected():
                    cancelled = True
                    logger.info(
                        "stream chat client disconnected: session_id=%s reply_len=%d",
                        current_session_id, len(full_reply),
                    )
                    break

                full_reply += token
                # token 含换行时直接拼会破坏 SSE 协议,先包成 JSON 再写入
                event_payload = StreamTokenEvent(token=token).model_dump_json()
                yield f"data: {event_payload}\n\n"

            if not cancelled:
                await chat_service.persist_assistant(
                    session_id=current_session_id,
                    content=full_reply,
                )
                logger.info(
                    "stream chat done: session_id=%s reply_len=%d",
                    current_session_id, len(full_reply),
                )

        except asyncio.CancelledError:
            # 客户端断开 / 服务端 shutdown 时由 Starlette 抛出,必须 raise 出去
            logger.info(
                "stream chat cancelled: session_id=%s reply_len=%d",
                current_session_id, len(full_reply),
            )
            raise

        except Exception as exc:  # noqa: BLE001 —— 流内任何异常都要先发给前端
            logger.exception("stream chat failed: session_id=%s", current_session_id)
            error_payload = StreamErrorEvent(error=_safe_stream_error(exc)).model_dump_json()
            yield f"data: {error_payload}\n\n"

        finally:
            if not cancelled:
                yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Session-ID": str(current_session_id),
        },
    )
