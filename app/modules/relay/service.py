"""Relay service boundary: orchestrate auth → channel → upstream → response.

The relay module wraps the existing channel pool and failover logic to expose
a vanilla OpenAI-compatible /v1/chat/completions endpoint. It reuses the same
provider dispatch patterns as the internal chat module but sends the full
messages array directly to upstream instead of building it from a single
user-message + history.
"""

from __future__ import annotations

import json
import logging
from typing import AsyncGenerator

import httpx

from app.core.config import settings
from app.modules.ai_providers.service import get_http_client
from app.modules.channels import service as channels_service
from app.modules.channels.schemas import ChannelConfig
from app.modules.relay.schemas import (
    ChatChoice,
    ChatChunkChoice,
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatDelta,
    ChatMessageResponse,
    ChatUsage,
    _completion_id,
    _now_ts,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request builder
# ---------------------------------------------------------------------------


def _build_payload(
    channel: ChannelConfig,
    request: ChatCompletionRequest,
    *,
    stream: bool,
) -> tuple[str, dict, dict]:
    """Build (url, headers, json_payload) for the upstream HTTP call."""
    actual_model = request.model
    # Apply model redirect if configured
    if channel.model_redirect and actual_model in channel.model_redirect:
        actual_model = channel.model_redirect[actual_model]

    url = f"{channel.base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {channel.api_key}",
        "Content-Type": "application/json",
    }
    payload: dict = {
        "model": actual_model,
        "messages": [m.model_dump(exclude_none=True) for m in request.messages],
        "stream": stream,
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    if request.top_p is not None:
        payload["top_p"] = request.top_p
    if request.frequency_penalty is not None:
        payload["frequency_penalty"] = request.frequency_penalty
    if request.presence_penalty is not None:
        payload["presence_penalty"] = request.presence_penalty
    if request.stop is not None:
        payload["stop"] = request.stop
    return url, headers, payload


# ---------------------------------------------------------------------------
# Error classification (same logic as openai_compat._classify_error)
# ---------------------------------------------------------------------------


def _classify_error(exc: Exception) -> tuple[str, bool]:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code == 429 or status_code >= 500:
            return f"http_{status_code}", True
        return f"http_{status_code}", False
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError)):
        return type(exc).__name__, True
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json", True
    return type(exc).__name__, True


async def _raise_pool_exhausted(failures: list[object]) -> None:
    if failures:
        logger.warning("relay channel pool exhausted: failures=%s", failures)
    raise channels_service.ChannelPoolError(
        "所有上游 channel 都不可用,请稍后重试或检查通道配置"
    )


# ---------------------------------------------------------------------------
# Non-streaming handler
# ---------------------------------------------------------------------------


async def handle_chat_completion(request: ChatCompletionRequest) -> ChatCompletionResponse:
    """Non-streaming: select channel → POST upstream → return OpenAI JSON."""
    tried_ids: set[str] = set()
    failures: list[object] = []

    while True:
        try:
            channel = await channels_service.select_channel(exclude_ids=tried_ids)
        except channels_service.ChannelPoolError:
            await _raise_pool_exhausted(failures)

        tried_ids.add(channel.id)
        url, headers, payload = _build_payload(channel, request, stream=False)

        logger.info(
            "relay non-stream: channel=%s model=%s messages=%d",
            channel.safe_label(), payload["model"], len(request.messages),
        )

        try:
            client = get_http_client()
            resp = await client.post(
                url, json=payload, headers=headers, timeout=settings.REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()

            await channels_service.mark_success(channel)
            logger.info("relay non-stream done: channel=%s", channel.safe_label())

            return _build_response(request, data)

        except Exception as exc:
            reason, retryable = _classify_error(exc)
            snapshot = await channels_service.mark_failure(
                channel, reason=reason, retryable=retryable,
            )
            failures.append(snapshot.model_dump())


def _build_response(request: ChatCompletionRequest, upstream: dict) -> ChatCompletionResponse:
    """Convert upstream JSON to our OpenAI-compatible response shape."""
    completion_id = _completion_id()
    created = _now_ts()
    upstream_model = upstream.get("model", request.model)

    choices: list[ChatChoice] = []
    for raw_choice in upstream.get("choices") or []:
        msg = raw_choice.get("message") or {}
        choices.append(ChatChoice(
            index=raw_choice.get("index", 0),
            message=ChatMessageResponse(
                role=msg.get("role", "assistant"),
                content=msg.get("content") or "",
            ),
            finish_reason=raw_choice.get("finish_reason"),
        ))

    usage = None
    if "usage" in upstream:
        usage = ChatUsage(
            prompt_tokens=upstream["usage"].get("prompt_tokens", 0),
            completion_tokens=upstream["usage"].get("completion_tokens", 0),
            total_tokens=upstream["usage"].get("total_tokens", 0),
        )

    return ChatCompletionResponse(
        id=completion_id,
        created=created,
        model=upstream_model,
        choices=choices,
        usage=usage,
    )


# ---------------------------------------------------------------------------
# Streaming handler
# ---------------------------------------------------------------------------


async def stream_chat_completion(request: ChatCompletionRequest) -> AsyncGenerator[str, None]:
    """SSE streaming: yield OpenAI-compatible chunk lines.

    Yields raw SSE frames::
        data: {"id":"...","object":"chat.completion.chunk",...}\n\n
        data: [DONE]\n\n
    """
    tried_ids: set[str] = set()
    failures: list[object] = []
    completion_id = _completion_id()
    created = _now_ts()

    while True:
        try:
            channel = await channels_service.select_channel(exclude_ids=tried_ids)
        except channels_service.ChannelPoolError:
            await _raise_pool_exhausted(failures)
            return

        tried_ids.add(channel.id)
        url, headers, payload = _build_payload(channel, request, stream=True)

        logger.info(
            "relay stream: channel=%s model=%s messages=%d",
            channel.safe_label(), payload["model"], len(request.messages),
        )

        emitted = False
        upstream_model = payload["model"]
        try:
            client = get_http_client()
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

                    chunk: dict = json.loads(data)
                    upstream_model = chunk.get("model", upstream_model)
                    choices = chunk.get("choices") or []

                    relay_choices: list[ChatChunkChoice] = []
                    for raw_choice in choices:
                        delta = raw_choice.get("delta") or {}
                        relay_choices.append(ChatChunkChoice(
                            index=raw_choice.get("index", 0),
                            delta=ChatDelta(
                                role=delta.get("role"),
                                content=delta.get("content"),
                            ),
                            finish_reason=raw_choice.get("finish_reason"),
                        ))

                    relay_chunk = ChatCompletionChunk(
                        id=completion_id,
                        created=created,
                        model=upstream_model,
                        choices=relay_choices,
                    )
                    emitted = True
                    yield f"data: {relay_chunk.model_dump_json()}\n\n"

            await channels_service.mark_success(channel)
            logger.info("relay stream done: channel=%s", channel.safe_label())
            yield "data: [DONE]\n\n"
            return

        except Exception as exc:
            reason, retryable = _classify_error(exc)
            snapshot = await channels_service.mark_failure(
                channel, reason=reason, retryable=retryable,
            )
            failures.append(snapshot.model_dump())
            if emitted:
                raise channels_service.ChannelPoolError("上游流式响应中断,请重试") from exc
