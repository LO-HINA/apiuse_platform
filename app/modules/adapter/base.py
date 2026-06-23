"""Provider Adapter 抽象基类 + 注册表。

每个 Provider 类型实现自己的 Adapter，Relay 层通过 provider_type 查找。
Adapter 不关心调度策略，只关心"给定一个 channel，怎么向上游发请求、怎么解析响应、怎么分类错误"。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import AsyncGenerator

from app.modules.channels.schemas import ChannelConfig
from app.modules.relay.schemas import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Adapter 注册表
# ---------------------------------------------------------------------------

_registry: dict[str, "ProviderAdapter"] = {}


def register_adapter(adapter: "ProviderAdapter") -> None:
    """注册一个 ProviderAdapter 实例。"""
    _registry[adapter.provider_type] = adapter
    logger.info("adapter registered: provider_type=%s", adapter.provider_type)


def get_adapter(provider_type: str) -> "ProviderAdapter":
    """按 provider_type 查找 adapter。未找到抛 KeyError。"""
    if provider_type not in _registry:
        raise KeyError(
            f"no adapter registered for provider_type='{provider_type}'"
        )
    return _registry[provider_type]


# ---------------------------------------------------------------------------
# 抽象基类
# ---------------------------------------------------------------------------


class ProviderAdapter(ABC):
    """Provider 适配器基类。

    子类只需实现 3 个方法：

    - ``chat_completion``: 非流式请求，返回完整响应
    - ``chat_completion_stream``: 流式请求，yield SSE 帧字符串
    - ``classify_error``: 把异常归为 (reason, retryable)
    """

    @property
    @abstractmethod
    def provider_type(self) -> str:
        """返回此 adapter 对应的 provider_type，如 ``"openai_compat"``。"""
        ...

    @abstractmethod
    async def chat_completion(
        self,
        channel: ChannelConfig,
        request: ChatCompletionRequest,
    ) -> ChatCompletionResponse:
        """非流式：构造请求 → 发送 → 解析上游 JSON → 返回 OpenAI 兼容响应。"""
        ...

    @abstractmethod
    async def chat_completion_stream(
        self,
        channel: ChannelConfig,
        request: ChatCompletionRequest,
        *,
        completion_id: str,
        created: int,
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        """流式：构造请求 → 流式发送 → 逐行解析 SSE → yield ChatCompletionChunk。

        每个 chunk 是纯数据对象，调用方自行决定如何格式化（SSE 帧 / token 文本）。
        """
        ...

    @staticmethod
    @abstractmethod
    def classify_error(exc: Exception) -> tuple[str, bool]:
        """把异常归为 ``(reason: str, retryable: bool)``。

        reason 是安全枚举（http_500 / ConnectError / invalid_json 等），
        不得包含上游 URL、API Key、响应体等敏感信息。
        """
        ...
