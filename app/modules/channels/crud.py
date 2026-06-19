"""JSON CRUD for channel accounts."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.modules.channels.schemas import ChannelConfig

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
_CHANNELS_FILE = _DATA_DIR / "channels.json"
_AUTH_DIR = _DATA_DIR / "channels" / "auth"

_channels: dict[str, ChannelConfig] = {}
_sources: dict[str, Path] = {}
_lock = asyncio.Lock()
_loaded = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_payload(raw: object) -> list[object]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("channels"), list):
        return raw["channels"]
    if isinstance(raw, dict):
        return [raw]
    raise ValueError("channel json must be an object, list, or {'channels': [...]}")


def _safe_file_stem(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip(".-")
    return normalized or "channel"


def _normalize_item(item: object, *, default_id: str | None = None) -> object:
    if not isinstance(item, dict):
        return item

    data = dict(item)
    if "base_url" not in data and "url" in data:
        data["base_url"] = data["url"]
    if "api_key" not in data and "key" in data:
        data["api_key"] = data["key"]
    if "id" not in data and default_id:
        data["id"] = default_id
    if "name" not in data and data.get("id"):
        data["name"] = data["id"]

    models = data.get("models")
    if isinstance(models, str):
        data["models"] = [
            model.strip()
            for model in re.split(r"[,|;\n]+", models)
            if model.strip()
        ]
    return data


def _load_file(file_path: Path, *, default_id: str | None = None) -> int:
    raw = json.loads(file_path.read_text(encoding="utf-8-sig"))
    loaded_count = 0
    for item in _coerce_payload(raw):
        normalized = _normalize_item(item, default_id=default_id)
        try:
            channel = ChannelConfig.model_validate(normalized)
        except Exception:  # noqa: BLE001 - never log raw key material
            label = normalized.get("id", "?") if isinstance(normalized, dict) else "?"
            logger.warning("channel config skipped: id=%s reason=validation_error", label)
            continue
        if channel.id in _channels:
            logger.info("channel config override: id=%s source=%s", channel.id, file_path.name)
        _channels[channel.id] = channel
        _sources[channel.id] = file_path
        loaded_count += 1
    return loaded_count


def load() -> None:
    """Load legacy channels.json and data/channels/auth/*.json once."""
    global _loaded
    if _loaded:
        return

    _channels.clear()
    _sources.clear()
    legacy_count = 0
    auth_count = 0

    if _CHANNELS_FILE.exists():
        try:
            legacy_count = _load_file(_CHANNELS_FILE)
        except (json.JSONDecodeError, ValueError):
            logger.warning("legacy channels file skipped: reason=invalid_json")

    if _AUTH_DIR.exists():
        for file_path in sorted(_AUTH_DIR.glob("*.json")):
            try:
                auth_count += _load_file(file_path, default_id=file_path.stem)
            except (json.JSONDecodeError, ValueError):
                logger.warning("channel auth file skipped: file=%s reason=invalid_json", file_path.name)

    _loaded = True
    logger.info(
        "channels loaded: total=%d legacy=%d auth=%d",
        len(_channels), legacy_count, auth_count,
    )


def _dump_channel(channel: ChannelConfig) -> dict:
    payload = channel.model_dump(mode="json")
    payload["url"] = payload.pop("base_url")
    payload["key"] = payload.pop("api_key")
    return payload


def _ensure_layout_unlocked() -> None:
    _AUTH_DIR.mkdir(parents=True, exist_ok=True)
    if not _CHANNELS_FILE.exists():
        _CHANNELS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CHANNELS_FILE.with_suffix(_CHANNELS_FILE.suffix + ".tmp")
        tmp.write_text("[]\n", encoding="utf-8")
        tmp.replace(_CHANNELS_FILE)


def _flush_path_unlocked(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ids = sorted(channel_id for channel_id, source in _sources.items() if source == path)
    payload_items = [_dump_channel(_channels[channel_id]) for channel_id in ids]
    payload: object
    if path == _CHANNELS_FILE or len(payload_items) != 1:
        payload = payload_items
    else:
        payload = payload_items[0]

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def count() -> int:
    return len(_channels)


async def list_all() -> list[ChannelConfig]:
    async with _lock:
        return list(_channels.values())


async def get(channel_id: str) -> ChannelConfig | None:
    async with _lock:
        return _channels.get(channel_id)


async def create(channel: ChannelConfig) -> ChannelConfig:
    async with _lock:
        if channel.id in _channels:
            raise ValueError("channel id already exists")

        _ensure_layout_unlocked()
        file_path = _AUTH_DIR / f"{_safe_file_stem(channel.id)}.json"
        if file_path.exists():
            raise ValueError("channel file already exists")

        _channels[channel.id] = channel
        _sources[channel.id] = file_path
        _flush_path_unlocked(file_path)
        return channel


async def mark_success(channel_id: str) -> None:
    async with _lock:
        channel = _channels.get(channel_id)
        if channel is None:
            return
        channel.success_count += 1
        channel.blacklisted_until = None
        channel.updated_at = _now()
        _flush_path_unlocked(_sources[channel_id])


async def mark_failure(
    channel_id: str,
    *,
    retryable: bool,
    blacklist_seconds: int,
) -> None:
    async with _lock:
        channel = _channels.get(channel_id)
        if channel is None:
            return
        channel.failure_count += 1
        if retryable and blacklist_seconds > 0:
            channel.blacklisted_until = _now() + timedelta(seconds=blacklist_seconds)
        channel.updated_at = _now()
        _flush_path_unlocked(_sources[channel_id])
