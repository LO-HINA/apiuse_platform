"""Relay router: POST /v1/chat/completions with API Key auth."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.deps import verify_api_key_dep
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
                async for frame in relay_service.stream_chat_completion(body, api_key_id=api_key_config.id):
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
        response = await relay_service.handle_chat_completion(body, api_key_id=api_key_config.id)
    except ChannelPoolError as exc:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.safe_message,
        )
    return response
