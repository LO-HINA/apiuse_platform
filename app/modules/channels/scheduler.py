"""Channel 调度算法。

这里故意保持很小:过滤不可用 channel,然后按 weight 做加权随机。
failover 的"本次请求已试过哪些 channel"由 service/openai_compat 传入 exclude_ids。
"""
from __future__ import annotations

import random
from datetime import datetime, timezone
from random import Random

from app.modules.channels.schemas import ChannelConfig


def _now() -> datetime:
    return datetime.now(timezone.utc)


def usable_channels(
    channels: list[ChannelConfig],
    *,
    exclude_ids: set[str] | None = None,
    now: datetime | None = None,
) -> list[ChannelConfig]:
    """过滤掉 disabled、已尝试、仍在黑名单窗口内的 channel。"""
    excluded = exclude_ids or set()
    current = now or _now()
    usable: list[ChannelConfig] = []
    for channel in channels:
        if channel.id in excluded:
            continue
        if not channel.enabled:
            continue
        if channel.blacklisted_until and channel.blacklisted_until > current:
            continue
        if channel.weight <= 0:
            continue
        usable.append(channel)
    return usable


def pick_weighted(
    channels: list[ChannelConfig],
    *,
    rng: Random | None = None,
) -> ChannelConfig | None:
    """按 weight 随机选择一条 channel。空列表返回 None。"""
    if not channels:
        return None
    chooser = rng or random
    total = sum(channel.weight for channel in channels)
    cursor = chooser.uniform(0, total)
    upto = 0.0
    for channel in channels:
        upto += channel.weight
        if cursor <= upto:
            return channel
    return channels[-1]
