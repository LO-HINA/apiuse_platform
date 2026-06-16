"""Channel JSON CRUD。

M2 不引入数据库。channels.json 是本地敏感配置文件,包含上游 API Key,
已经由 `.gitignore` 的 `data/` 规则保护。这里不提供任何会把 api_key
返回给前端的函数。
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.modules.channels.schemas import ChannelConfig

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
_CHANNELS_FILE = _DATA_DIR / "channels.json"

_channels: dict[str, ChannelConfig] = {}
_lock = asyncio.Lock()
_loaded = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_payload(raw: object) -> list[object]:
    """兼容两种本地写法:直接数组,或 {"channels": [...]}。"""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("channels"), list):
        return raw["channels"]
    raise ValueError("channels.json must be a list or {'channels': [...]}")


def load() -> None:
    """启动期同步加载 channels.json;文件缺失时以空池启动。"""
    global _loaded
    if _loaded:
        return
    if not _CHANNELS_FILE.exists():
        _loaded = True
        logger.info("channels.json 不存在,以空 channel 池启动: %s", _CHANNELS_FILE)
        return

    raw = json.loads(_CHANNELS_FILE.read_text(encoding="utf-8-sig"))
    loaded: dict[str, ChannelConfig] = {}
    for item in _coerce_payload(raw):
        try:
            channel = ChannelConfig.model_validate(item)
        except Exception:  # noqa: BLE001 - 配置文件错误要定位,但不能打印 key
            label = item.get("id", "?") if isinstance(item, dict) else "?"
            logger.warning("channel config skipped: id=%s reason=validation_error", label)
            continue
        loaded[channel.id] = channel

    _channels.clear()
    _channels.update(loaded)
    _loaded = True
    logger.info("channels.json 加载完成: count=%d", len(_channels))


def _flush_unlocked() -> None:
    """原子写盘。调用方必须已经持有 _lock。"""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _CHANNELS_FILE.with_suffix(_CHANNELS_FILE.suffix + ".tmp")
    payload = [
        channel.model_dump(mode="json")
        for channel in sorted(_channels.values(), key=lambda c: c.id)
    ]
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_CHANNELS_FILE)


def count() -> int:
    """同步返回当前 channel 数量,供启动和 dispatch 检测用。"""
    return len(_channels)


async def list_all() -> list[ChannelConfig]:
    async with _lock:
        return list(_channels.values())


async def get(channel_id: str) -> ChannelConfig | None:
    async with _lock:
        return _channels.get(channel_id)


async def mark_success(channel_id: str) -> None:
    """记录成功并清掉过期/历史黑名单。"""
    async with _lock:
        channel = _channels.get(channel_id)
        if channel is None:
            return
        channel.success_count += 1
        channel.blacklisted_until = None
        channel.updated_at = _now()
        _flush_unlocked()


async def mark_failure(
    channel_id: str,
    *,
    retryable: bool,
    blacklist_seconds: int,
) -> None:
    """记录失败;只有 retryable 失败才临时拉黑。"""
    async with _lock:
        channel = _channels.get(channel_id)
        if channel is None:
            return
        channel.failure_count += 1
        if retryable and blacklist_seconds > 0:
            channel.blacklisted_until = _now() + timedelta(seconds=blacklist_seconds)
        channel.updated_at = _now()
        _flush_unlocked()
