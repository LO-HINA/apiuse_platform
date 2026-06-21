"""SQLite CRUD for channel accounts."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from app.core.crypto import decrypt, encrypt
from app.core.database import get_db
from app.modules.channels.schemas import ChannelConfig

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_channel(row) -> ChannelConfig:
    """将 SQLite 行转为 ChannelConfig Pydantic 模型。"""
    raw_key = row["api_key"]
    try:
        decrypted_key = decrypt(raw_key) if raw_key else raw_key
    except Exception:
        decrypted_key = raw_key  # 兼容迁移前未加密的旧数据
    return ChannelConfig(
        id=row["id"],
        name=row["name"],
        provider_type=row["provider_type"],
        base_url=row["base_url"],
        api_key=decrypted_key,
        organization=row["organization"],
        models=json.loads(row["models"]) if row["models"] else [],
        group=row["group"],
        model_redirect=json.loads(row["model_redirect"]) if row["model_redirect"] else {},
        weight=row["weight"],
        enabled=bool(row["enabled"]),
        success_count=row["success_count"],
        failure_count=row["failure_count"],
        blacklisted_until=(
            datetime.fromisoformat(row["blacklisted_until"])
            if row["blacklisted_until"]
            else None
        ),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def load() -> None:
    """占位:SQLite 建表已在 init_db() 完成,此函数不再需要加载 JSON。"""
    logger.debug("channels load skipped — using SQLite persistence")


async def count() -> int:
    db = get_db()
    cursor = await db.execute("SELECT COUNT(*) AS cnt FROM channels")
    row = await cursor.fetchone()
    await cursor.close()
    return row["cnt"]


async def list_all() -> list[ChannelConfig]:
    db = get_db()
    cursor = await db.execute("SELECT * FROM channels ORDER BY created_at ASC")
    rows = await cursor.fetchall()
    await cursor.close()
    return [_row_to_channel(r) for r in rows]


async def get(channel_id: str) -> ChannelConfig | None:
    db = get_db()
    cursor = await db.execute("SELECT * FROM channels WHERE id = ?", (channel_id,))
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        return None
    return _row_to_channel(row)


async def create(channel: ChannelConfig) -> ChannelConfig:
    db = get_db()
    async with _lock:
        # 查重
        cursor = await db.execute("SELECT 1 FROM channels WHERE id = ?", (channel.id,))
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            raise ValueError("channel id already exists")

        now = _now_iso()
        created_at = (
            channel.created_at.isoformat()
            if channel.created_at.tzinfo
            else channel.created_at.replace(tzinfo=timezone.utc).isoformat()
        )
        updated_at = (
            channel.updated_at.isoformat()
            if channel.updated_at.tzinfo
            else channel.updated_at.replace(tzinfo=timezone.utc).isoformat()
        )
        blacklisted_until = (
            channel.blacklisted_until.isoformat()
            if channel.blacklisted_until
            else None
        )

        await db.execute(
            "INSERT INTO channels "
            "(id, name, provider_type, base_url, api_key, organization, \"group\", "
            "models, model_redirect, weight, enabled, success_count, failure_count, "
            "blacklisted_until, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                channel.id,
                channel.name,
                channel.provider_type,
                channel.base_url,
                encrypt(channel.api_key) if channel.api_key else "",
                channel.organization,
                channel.group,
                json.dumps(channel.models, ensure_ascii=False),
                json.dumps(channel.model_redirect, ensure_ascii=False),
                channel.weight,
                int(channel.enabled),
                channel.success_count,
                channel.failure_count,
                blacklisted_until,
                created_at,
                updated_at,
            ),
        )
        await db.commit()

    return channel


async def mark_success(channel_id: str) -> None:
    now = _now_iso()
    db = get_db()
    async with _lock:
        await db.execute(
            "UPDATE channels SET success_count = success_count + 1, "
            "blacklisted_until = NULL, updated_at = ? "
            "WHERE id = ?",
            (now, channel_id),
        )
        await db.commit()


async def mark_failure(
    channel_id: str,
    *,
    retryable: bool,
    blacklist_seconds: int,
) -> None:
    now = _now_iso()
    blacklisted_until = (
        (_now() + timedelta(seconds=blacklist_seconds)).isoformat()
        if retryable and blacklist_seconds > 0
        else None
    )
    db = get_db()
    async with _lock:
        if blacklisted_until is not None:
            await db.execute(
                "UPDATE channels SET failure_count = failure_count + 1, "
                "blacklisted_until = ?, updated_at = ? "
                "WHERE id = ?",
                (blacklisted_until, now, channel_id),
            )
        else:
            await db.execute(
                "UPDATE channels SET failure_count = failure_count + 1, "
                "updated_at = ? "
                "WHERE id = ?",
                (now, channel_id),
            )
        await db.commit()
