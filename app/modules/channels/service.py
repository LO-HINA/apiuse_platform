"""Channel 业务服务。

这里是 M2 号池的公共边界:加载本地 JSON、选择可用 channel、记录成功/失败。
provider 层只关心"给我一条可用 channel"和"这次调用结果如何"。
"""
from __future__ import annotations

import logging

from app.core.config import settings
from app.modules.channels import crud, scheduler
from app.modules.channels.schemas import ChannelConfig, ChannelFailureSnapshot

logger = logging.getLogger(__name__)


class ChannelPoolError(Exception):
    """channel 池不可用。message 必须是可返回给用户的安全文本。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.safe_message = message


def load_channels() -> None:
    crud.load()


async def select_channel(*, exclude_ids: set[str] | None = None) -> ChannelConfig:
    channels = await crud.list_all()
    usable = scheduler.usable_channels(channels, exclude_ids=exclude_ids)
    selected = scheduler.pick_weighted(usable)
    if selected is None:
        raise ChannelPoolError("没有可用的上游 channel,请检查 channels.json 或等待黑名单过期")
    logger.info("channel selected: channel=%s", selected.safe_label())
    return selected


async def mark_success(channel: ChannelConfig) -> None:
    await crud.mark_success(channel.id)
    logger.info("channel success: channel=%s", channel.safe_label())


async def mark_failure(
    channel: ChannelConfig,
    *,
    reason: str,
    retryable: bool,
) -> ChannelFailureSnapshot:
    await crud.mark_failure(
        channel.id,
        retryable=retryable,
        blacklist_seconds=settings.CHANNEL_BLACKLIST_SECONDS,
    )
    snapshot = ChannelFailureSnapshot(
        channel_id=channel.id,
        name=channel.name,
        reason=reason,
        retryable=retryable,
    )
    logger.warning(
        "channel failure: channel=%s reason=%s retryable=%s",
        channel.safe_label(), reason, retryable,
    )
    return snapshot
