"""OpenAI 兼容协议实现:POST /chat/completions,流式 / 非流式两路。

M2 起真实上游调用走 channel 池。这里不再直接用全局 AI_BASE_URL / AI_API_KEY
作为唯一上游,而是每次选择一条 channel,失败后按规则记录并尝试下一条。
"""
from __future__ import annotations

import json
import logging
from typing import AsyncGenerator, Optional, Sequence

import httpx

from app.core.config import settings
from app.modules.ai_providers.service import build_messages, get_http_client
from app.modules.channels import service as channels_service
from app.modules.channels.schemas import ChannelConfig
from app.modules.messages.schemas import Message

logger = logging.getLogger(__name__)


def _request_payload(
    channel: ChannelConfig,
    *,
    message: str,
    history: Optional[Sequence[Message]],
    stream: bool,
) -> tuple[str, dict, dict]:
    """构造请求三件套。headers 只交给 httpx,不要写日志。"""
    model = channel.model_for_request(settings.AI_MODEL)
    url = f"{channel.base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {channel.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": build_messages(message, history),
        "stream": stream,
    }
    return url, headers, payload


def _classify_error(exc: Exception) -> tuple[str, bool]:
    """把 provider 异常压成安全 reason + 是否临时拉黑。

    reason 只能写安全枚举,不能包含 URL、Authorization、响应体或用户 prompt。
    """
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
        logger.warning("channel pool exhausted: failures=%s", failures)
    raise channels_service.ChannelPoolError(
        "所有上游 channel 都不可用,请稍后重试或检查 channels.json"
    )


async def _real_ai_stream_once(
    channel: ChannelConfig,
    *,
    message: str,
    history: Optional[Sequence[Message]],
) -> AsyncGenerator[str, None]:
    """对单个 channel 发起一次流式请求。失败分类由外层 failover 处理。"""
    client = get_http_client()
    url, headers, payload = _request_payload(
        channel, message=message, history=history, stream=True,
    )
    logger.info(
        "real_ai_stream calling: channel=%s model=%s",
        channel.safe_label(), payload["model"],
    )

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
            chunk = json.loads(data)
            choices = chunk.get("choices") or []
            if not choices:
                continue
            token = (choices[0].get("delta") or {}).get("content")
            if token:
                yield token


async def real_ai_stream(
    message: str, history: Optional[Sequence[Message]] = None,
) -> AsyncGenerator[str, None]:
    """stream=true 逐行解析 SSE,只透传 delta.content。

    failover 只发生在尚未向浏览器发 token 前。一旦已经发出 token,
    中途换 channel 会导致重复输出,所以改为安全报错。
    """
    tried_ids: set[str] = set()
    failures: list[object] = []

    while True:
        try:
            channel = await channels_service.select_channel(exclude_ids=tried_ids)
        except channels_service.ChannelPoolError:
            await _raise_pool_exhausted(failures)

        tried_ids.add(channel.id)
        emitted = False
        try:
            async for token in _real_ai_stream_once(channel, message=message, history=history):
                emitted = True
                yield token
            await channels_service.mark_success(channel)
            logger.info("real_ai_stream done: channel=%s", channel.safe_label())
            return
        except Exception as exc:
            reason, retryable = _classify_error(exc)
            snapshot = await channels_service.mark_failure(
                channel, reason=reason, retryable=retryable,
            )
            failures.append(snapshot.model_dump())
            if emitted:
                raise channels_service.ChannelPoolError("上游流式响应中断,请重试") from exc


async def _real_ai_reply_once(
    channel: ChannelConfig,
    *,
    message: str,
    history: Optional[Sequence[Message]],
) -> str:
    """对单个 channel 发起一次非流式请求。"""
    client = get_http_client()
    url, headers, payload = _request_payload(
        channel, message=message, history=history, stream=False,
    )
    logger.info(
        "real_ai_reply calling: channel=%s model=%s",
        channel.safe_label(), payload["model"],
    )

    resp = await client.post(url, json=payload, headers=headers, timeout=settings.REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("upstream returned no choices")
    return (choices[0].get("message") or {}).get("content") or ""


async def real_ai_reply(
    message: str, history: Optional[Sequence[Message]] = None,
) -> str:
    """非流式版,一次性拿完整 JSON。失败会尝试下一条 channel。"""
    tried_ids: set[str] = set()
    failures: list[object] = []

    while True:
        try:
            channel = await channels_service.select_channel(exclude_ids=tried_ids)
        except channels_service.ChannelPoolError:
            await _raise_pool_exhausted(failures)

        tried_ids.add(channel.id)
        try:
            reply = await _real_ai_reply_once(channel, message=message, history=history)
            await channels_service.mark_success(channel)
            return reply
        except Exception as exc:
            reason, retryable = _classify_error(exc)
            snapshot = await channels_service.mark_failure(
                channel, reason=reason, retryable=retryable,
            )
            failures.append(snapshot.model_dump())
