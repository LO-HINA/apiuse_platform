"""OpenAI 兼容协议 Adapter 实现。

处理与 OpenAI-compatible 上游的 HTTP 通信：构造请求、发起调用、
解析 JSON/SSE 响应、错误分类。

仅负责"给定 channel 怎么请求上游"——不关心调度、不关心配额、不关心日志。
"""

from __future__ import annotations

import json
import logging
from typing import AsyncGenerator

import httpx

from app.core.config import settings
from app.modules.adapter.base import ProviderAdapter
from app.modules.adapter.service import get_http_client
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


class UpstreamFormatError(Exception):
    """上游返回了非预期的响应格式（如 HTML 而非 SSE/JSON）。"""


# ---------------------------------------------------------------------------
# Adapter 实现
# ---------------------------------------------------------------------------


class OpenAICompatAdapter(ProviderAdapter):
    provider_type = "openai_compat"

    # -----------------------------------------------------------------------
    # 错误分类
    # -----------------------------------------------------------------------

    @staticmethod
    def classify_error(exc: Exception) -> tuple[str, bool]:
        """把 provider 异常压成安全 reason + retryable 标记。"""
        if isinstance(exc, httpx.HTTPStatusError):
            status_code = exc.response.status_code
            if status_code == 429 or status_code >= 500:
                return f"http_{status_code}", True
            return f"http_{status_code}", False
        if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError)):
            return type(exc).__name__, True
        if isinstance(exc, (json.JSONDecodeError, UpstreamFormatError)):
            return "invalid_response", True
        return type(exc).__name__, True

    # -----------------------------------------------------------------------
    # 非流式
    # -----------------------------------------------------------------------

    async def chat_completion(
        self,
        channel: ChannelConfig,
        request: ChatCompletionRequest,
    ) -> ChatCompletionResponse:
        url, headers, payload = self._build_payload(channel, request, stream=False)

        logger.info(
            "openai_adapter non-stream: channel=%s model=%s messages=%d",
            channel.safe_label(), payload["model"], len(request.messages),
        )

        client = get_http_client()
        resp = await client.post(
            url, json=payload, headers=headers, timeout=settings.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        logger.info("openai_adapter non-stream done: channel=%s", channel.safe_label())
        return self._build_response(request, data)

    # -----------------------------------------------------------------------
    # 流式
    # -----------------------------------------------------------------------

    async def chat_completion_stream(
        self,
        channel: ChannelConfig,
        request: ChatCompletionRequest,
        *,
        completion_id: str,
        created: int,
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        url, headers, payload = self._build_payload(channel, request, stream=True)

        logger.info(
            "openai_adapter stream: channel=%s model=%s messages=%d",
            channel.safe_label(), payload["model"], len(request.messages),
        )

        upstream_model = payload["model"]
        client = get_http_client()
        raw_lines = 0
        chunk_count = 0
        _sample_non_data: list[str] = []
        _sample_json_err: list[str] = []
        async with client.stream(
            "POST", url, json=payload, headers=headers, timeout=settings.REQUEST_TIMEOUT,
        ) as resp:
            resp.raise_for_status()

            async for line in resp.aiter_lines():
                raw_lines += 1
                if not line or not line.startswith("data: "):
                    if len(_sample_non_data) < 3:
                        _sample_non_data.append(line[:200])
                    continue
                data = line[len("data: "):].strip()
                if data == "[DONE]":
                    break

                try:
                    chunk: dict = json.loads(data)
                except json.JSONDecodeError:
                    if len(_sample_json_err) < 3:
                        _sample_json_err.append(data[:200])
                    continue
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
                chunk_count += 1
                yield relay_chunk

        if chunk_count == 0 and raw_lines > 0:
            logger.warning(
                "openai_adapter stream: channel=%s %d raw lines, 0 chunks. "
                "non-data samples=%s json-err samples=%s",
                channel.safe_label(), raw_lines,
                _sample_non_data, _sample_json_err,
            )
            raise UpstreamFormatError("上游返回了非预期的响应格式")
        logger.info("openai_adapter stream done: channel=%s", channel.safe_label())

    # -----------------------------------------------------------------------
    # 内部方法
    # -----------------------------------------------------------------------

    def _build_payload(
        self,
        channel: ChannelConfig,
        request: ChatCompletionRequest,
        *,
        stream: bool,
    ) -> tuple[str, dict, dict]:
        """构造 (url, headers, json_body) 三件套。"""
        actual_model = request.model
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

    def _build_response(
        self,
        request: ChatCompletionRequest,
        upstream: dict,
    ) -> ChatCompletionResponse:
        """上游 JSON → OpenAI ChatCompletionResponse。"""
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
