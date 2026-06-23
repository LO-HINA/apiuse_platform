"""Relay service boundary: orchestrate channel → adapter → response.

提供两个层次：
- 共享原语：``execute_stream`` / ``execute_non_stream`` — channel 选择 + failover + adapter
- 高层封装：``stream_chat_completion`` / ``handle_chat_completion`` — 供 relay router 用

Relay 只做调度编排。接受 api_key_config 时统一记录 call_logs + 累 used_quota。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

from app.core.database import get_db
from app.modules.adapter.base import get_adapter
from app.modules.api_keys import crud as api_keys_crud
from app.modules.channels import service as channels_service
from app.modules.relay.schemas import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    _completion_id,
    _now_ts,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# call_logs 记录
# ---------------------------------------------------------------------------

async def _log_call(
    api_key_id: str,
    model: str,
    *,
    stream: bool,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
) -> None:
    db = get_db()
    await db.execute(
        """INSERT INTO call_logs
           (id, api_key_id, model, stream, prompt_tokens, completion_tokens, total_tokens, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            str(uuid.uuid4()),
            api_key_id,
            model,
            1 if stream else 0,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    await db.commit()
    if total_tokens > 0:
        await api_keys_crud.increment_used_quota(api_key_id, total_tokens)


# ---------------------------------------------------------------------------
# 共享原语 — channel 选择 + failover + adapter 委托
# chat 和 relay 共用这一套
# ---------------------------------------------------------------------------


async def _raise_pool_exhausted(failures: list[object]) -> None:
    if failures:
        logger.warning("relay channel pool exhausted: failures=%s", failures)
    raise channels_service.ChannelPoolError(
        "所有上游 channel 都不可用，请稍后重试或检查通道配置"
    )


async def execute_non_stream(
    request: ChatCompletionRequest,
    *,
    api_key_id: str | None = None,
) -> ChatCompletionResponse:
    """非流式共享原语：选 channel → adapter → 返回完整响应 + 记录 call_logs。"""
    tried_ids: set[str] = set()
    failures: list[object] = []

    while True:
        try:
            channel = await channels_service.select_channel(exclude_ids=tried_ids)
        except channels_service.ChannelPoolError:
            await _raise_pool_exhausted(failures)

        tried_ids.add(channel.id)
        adapter = get_adapter(channel.provider_type)

        try:
            response = await adapter.chat_completion(channel, request)
            await channels_service.mark_success(channel)

            if api_key_id and response.usage and response.usage.total_tokens > 0:
                await _log_call(
                    api_key_id, request.model, stream=False,
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens,
                )

            logger.info("execute_non_stream done: channel=%s", channel.safe_label())
            return response

        except Exception as exc:
            reason, retryable = adapter.classify_error(exc)
            snapshot = await channels_service.mark_failure(
                channel, reason=reason, retryable=retryable,
            )
            failures.append(snapshot.model_dump())


async def execute_stream(
    request: ChatCompletionRequest,
    *,
    api_key_id: str | None = None,
) -> AsyncGenerator[ChatCompletionChunk, None]:
    """流式共享原语：选 channel → adapter 流式调用 → yield ChatCompletionChunk。

    已产出 chunk 后失败不切换 channel（防止重复输出），直接抛异常。
    流式结束后自动记录 call_logs（token 数从最后一个有 usage 的 chunk 取，无则 0）。
    """
    tried_ids: set[str] = set()
    failures: list[object] = []
    completion_id = _completion_id()
    created = _now_ts()
    _usage: dict | None = None

    while True:
        try:
            channel = await channels_service.select_channel(exclude_ids=tried_ids)
        except channels_service.ChannelPoolError:
            await _raise_pool_exhausted(failures)
            return

        tried_ids.add(channel.id)
        adapter = get_adapter(channel.provider_type)
        emitted = False
        try:
            async for chunk in adapter.chat_completion_stream(
                channel, request,
                completion_id=completion_id,
                created=created,
            ):
                emitted = True
                yield chunk

            await channels_service.mark_success(channel)

            if api_key_id:
                usage = _usage or {}
                await _log_call(
                    api_key_id, request.model, stream=True,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                )

            logger.info("execute_stream done: channel=%s", channel.safe_label())
            return

        except Exception as exc:
            reason, retryable = adapter.classify_error(exc)
            snapshot = await channels_service.mark_failure(
                channel, reason=reason, retryable=retryable,
            )
            failures.append(snapshot.model_dump())
            if emitted:
                raise channels_service.ChannelPoolError("上游流式响应中断，请重试") from exc


# ---------------------------------------------------------------------------
# 高层封装 — 供 relay router 直接使用
# ---------------------------------------------------------------------------


async def handle_chat_completion(
    request: ChatCompletionRequest,
    *,
    api_key_id: str | None = None,
) -> ChatCompletionResponse:
    return await execute_non_stream(request, api_key_id=api_key_id)


async def stream_chat_completion(
    request: ChatCompletionRequest,
    *,
    api_key_id: str | None = None,
) -> AsyncGenerator[str, None]:
    async for chunk in execute_stream(request, api_key_id=api_key_id):
        yield f"data: {chunk.model_dump_json()}\n\n"
    yield "data: [DONE]\n\n"
