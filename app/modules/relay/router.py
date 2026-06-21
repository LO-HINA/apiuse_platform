"""Relay router: POST /v1/chat/completions with API Key auth."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.deps import verify_api_key_dep
from app.core.database import get_db
from app.modules.api_keys import crud as api_keys_crud
from app.modules.api_keys.schemas import ApiKeyConfig
from app.modules.channels.service import ChannelPoolError
from app.modules.relay.schemas import ChatCompletionRequest, ChatCompletionResponse
from app.modules.relay import service as relay_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["relay"])


def _safe_stream_error(exc: Exception) -> str:
    safe_message = getattr(exc, "safe_message", None)
    if isinstance(safe_message, str) and safe_message:
        return safe_message
    return "流式响应失败,请稍后重试"


@router.post("/chat/completions", response_model=None)
async def chat_completions(
    request: Request,
    body: ChatCompletionRequest,
    api_key_config: Annotated[ApiKeyConfig, Depends(verify_api_key_dep)],
):
    """OpenAI-compatible chat completions endpoint.

    - ``stream=false`` → standard JSON ``ChatCompletionResponse``
    - ``stream=true``  → SSE ``text/event-stream`` with chunk events
    """
    logger.info(
        "relay request: model=%s stream=%s messages=%d key_id=%s",
        body.model, body.stream, len(body.messages), api_key_config.id,
    )

    # Quota check
    if api_key_config.quota > 0 and api_key_config.used_quota >= api_key_config.quota:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="API Key 额度已用完",
        )

    if body.stream:
        async def event_generator():
            cancelled = False
            try:
                async for frame in relay_service.stream_chat_completion(body):
                    if await request.is_disconnected():
                        cancelled = True
                        logger.info("relay stream client disconnected: key=%s", api_key_config.id)
                        break
                    yield frame

            except asyncio.CancelledError:
                logger.info("relay stream cancelled: key=%s", api_key_config.id)
                raise

            except ChannelPoolError as exc:
                logger.warning("relay stream channel pool error: key=%s", api_key_config.id)
                error_payload = json.dumps({"error": _safe_stream_error(exc)})
                yield f"data: {error_payload}\n\n"
                if not cancelled:
                    yield "data: [DONE]\n\n"

            except Exception as exc:
                logger.exception("relay stream failed: key=%s", api_key_config.id)
                error_payload = json.dumps({"error": _safe_stream_error(exc)})
                yield f"data: {error_payload}\n\n"
                if not cancelled:
                    yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    # Non-streaming
    try:
        response = await relay_service.handle_chat_completion(body)
    except ChannelPoolError as exc:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.safe_message,
        )
    # Track token usage
    if response.usage and response.usage.total_tokens > 0:
        await api_keys_crud.increment_used_quota(api_key_config.id, response.usage.total_tokens)
        db = get_db()
        await db.execute(
            """INSERT INTO call_logs
               (id, api_key_id, model, stream, prompt_tokens, completion_tokens, total_tokens, created_at)
               VALUES (?, ?, ?, 0, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                api_key_config.id,
                body.model,
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
                response.usage.total_tokens,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await db.commit()
    return response
