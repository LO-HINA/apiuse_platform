"""Anthropic 协议 Adapter 实现。

将 Anthropic Messages API 适配为 OpenAI-compatible 接口：
- 请求转换：OpenAI messages → Anthropic messages + system + max_tokens
- 响应转换：Anthropic content[0].text → choices[0].message.content
- 流式转换：event: content_block_delta → ChatCompletionChunk
- 错误分类：529 overload → retryable
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


class AnthropicFormatError(Exception):
    """Anthropic 上游返回了非预期的响应格式。"""


class AnthropicCompatAdapter(ProviderAdapter):
    provider_type = "anthropic"

    # -----------------------------------------------------------------------
    # 错误分类
    # -----------------------------------------------------------------------

    @staticmethod
    def classify_error(exc: Exception) -> tuple[str, bool]:
        if isinstance(exc, httpx.HTTPStatusError):
            status_code = exc.response.status_code
            # Anthropic 529 = overloaded，可重试
            if status_code in (429, 529) or status_code >= 500:
                return f"http_{status_code}", True
            return f"http_{status_code}", False
        if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError)):
            return type(exc).__name__, True
        if isinstance(exc, (json.JSONDecodeError, AnthropicFormatError)):
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
            "anthropic_adapter non-stream: channel=%s model=%s messages=%d",
            channel.safe_label(), payload.get("model"), len(request.messages),
        )

        client = get_http_client()
        resp = await client.post(
            url, json=payload, headers=headers, timeout=settings.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        logger.info("anthropic_adapter non-stream done: channel=%s", channel.safe_label())
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
            "anthropic_adapter stream: channel=%s model=%s messages=%d",
            channel.safe_label(), payload.get("model"), len(request.messages),
        )

        client = get_http_client()
        raw_lines = 0
        chunk_count = 0
        _sample_non_data: list[str] = []
        _sample_json_err: list[str] = []

        # Anthropic SSE 用 event: 行区分事件类型，需要跨行缓冲
        _event_type: str | None = None

        async with client.stream(
            "POST", url, json=payload, headers=headers, timeout=settings.REQUEST_TIMEOUT,
        ) as resp:
            resp.raise_for_status()

            async for line in resp.aiter_lines():
                raw_lines += 1

                # Anthropic SSE: event: 行声明类型，data: 行是载荷
                if not line:
                    continue
                if line.startswith("event: "):
                    _event_type = line[len("event: "):].strip()
                    continue
                if not line.startswith("data: "):
                    if len(_sample_non_data) < 3:
                        _sample_non_data.append(line[:200])
                    continue

                raw_data = line[len("data: "):].strip()

                try:
                    event = json.loads(raw_data)
                except json.JSONDecodeError:
                    if len(_sample_json_err) < 3:
                        _sample_json_err.append(raw_data[:200])
                    continue

                event_type = event.get("type", _event_type or "")

                if event_type == "message_start":
                    continue

                if event_type == "content_block_delta":
                    delta = event.get("delta") or {}
                    text = delta.get("text") or ""

                    relay_chunk = ChatCompletionChunk(
                        id=completion_id,
                        created=created,
                        model=payload.get("model", request.model),
                        choices=[ChatChunkChoice(
                            index=event.get("index", 0),
                            delta=ChatDelta(content=text),
                        )],
                    )
                    chunk_count += 1
                    yield relay_chunk

                elif event_type in ("message_delta", "message_stop", "content_block_stop"):
                    pass

                else:
                    # 未识别的事件类型，忽略（ping 等）
                    pass

        if chunk_count == 0 and raw_lines > 0:
            logger.warning(
                "anthropic_adapter stream: channel=%s %d raw lines, 0 chunks. "
                "non-data samples=%s json-err samples=%s event=%s",
                channel.safe_label(), raw_lines,
                _sample_non_data, _sample_json_err, _event_type,
            )
            raise AnthropicFormatError("上游返回了非预期的响应格式")
        logger.info("anthropic_adapter stream done: channel=%s", channel.safe_label())

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
        """构造 Anthropic 格式的 (url, headers, body)。

        Anthropic 与 OpenAI 的关键差异：
        - URL: /messages（不是 /chat/completions）
        - 鉴权: x-api-key（不是 Authorization: Bearer）
        - system prompt 是顶层字段，不在 messages 里
        - max_tokens 必填
        """
        actual_model = request.model
        if channel.model_redirect and actual_model in channel.model_redirect:
            actual_model = channel.model_redirect[actual_model]

        url = f"{channel.base_url}/messages"
        headers = {
            "x-api-key": channel.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        # 分离 system prompt 和 messages
        system_prompts: list[str] = []
        messages: list[dict] = []
        for m in request.messages:
            if m.role == "system":
                system_prompts.append(
                    m.content if isinstance(m.content, str)
                    else json.dumps(m.content, ensure_ascii=False)
                )
            else:
                messages.append(self._convert_message(m))

        payload: dict = {
            "model": actual_model,
            "messages": messages,
            "max_tokens": request.max_tokens or 4096,  # Anthropic 必填
            "stream": stream,
        }
        if system_prompts:
            payload["system"] = "\n".join(system_prompts)
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.stop:
            payload["stop_sequences"] = (
                [request.stop] if isinstance(request.stop, str) else request.stop
            )

        return url, headers, payload

    @staticmethod
    def _convert_message(m: object) -> dict:
        """转换单条消息为 Anthropic 格式。"""
        role = m.role
        content = m.content

        # Anthropic 不需要 function/tool role
        if role in ("function", "tool"):
            role = "user"

        if isinstance(content, str):
            return {"role": role, "content": content}
        # 多模态 content（list[dict]）
        return {"role": role, "content": content}

    def _build_response(
        self,
        request: ChatCompletionRequest,
        upstream: dict,
    ) -> ChatCompletionResponse:
        """Anthropic 响应 → OpenAI ChatCompletionResponse。

        Anthropic 结构:
          content: [{"type": "text", "text": "Hello"}]
          stop_reason: "end_turn"
          usage: {input_tokens, output_tokens}
        """
        completion_id = _completion_id()
        created = _now_ts()
        upstream_model = upstream.get("model", request.model)

        # 提取文本内容
        text = ""
        for block in upstream.get("content") or []:
            if block.get("type") == "text":
                text += block.get("text", "")

        stop_reason = upstream.get("stop_reason", "stop")
        finish_reason = _map_stop_reason(stop_reason)

        choices: list[ChatChoice] = [
            ChatChoice(
                index=0,
                message=ChatMessageResponse(role="assistant", content=text),
                finish_reason=finish_reason,
            ),
        ]

        usage = None
        if "usage" in upstream:
            usage = ChatUsage(
                prompt_tokens=upstream["usage"].get("input_tokens", 0),
                completion_tokens=upstream["usage"].get("output_tokens", 0),
                total_tokens=(
                    upstream["usage"].get("input_tokens", 0)
                    + upstream["usage"].get("output_tokens", 0)
                ),
            )

        return ChatCompletionResponse(
            id=completion_id,
            created=created,
            model=upstream_model,
            choices=choices,
            usage=usage,
        )


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _map_stop_reason(reason: str) -> str:
    """Anthropic stop_reason → OpenAI finish_reason。"""
    mapping = {
        "end_turn": "stop",
        "max_tokens": "length",
        "stop_sequence": "stop",
        "tool_use": "tool_calls",
    }
    return mapping.get(reason, "stop")
