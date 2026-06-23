"""SQLite CRUD for API keys."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from app.core.database import get_db
from app.modules.api_keys.schemas import ApiKeyConfig

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_api_key_config(row) -> ApiKeyConfig:
    """将 SQLite 行转为 ApiKeyConfig Pydantic 模型。"""
    return ApiKeyConfig(
        id=row["id"],
        key_hash=row["key_hash"],
        key_prefix=row["key_prefix"],
        key_masked=row["key_masked"],
        key_encrypted=row["key_encrypted"] if "key_encrypted" in row.keys() else None,
        name=row["name"],
        models=json.loads(row["models"]) if row["models"] else [],
        quota=row["quota"],
        used_quota=row["used_quota"],
        status=row["status"],
        is_default=bool(row["is_default"]) if "is_default" in row.keys() else False,
        user_id=row["user_id"],
        expires_at=(
            datetime.fromisoformat(row["expires_at"])
            if row["expires_at"]
            else None
        ),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def load() -> None:
    """占位:SQLite 建表已在 init_db() 完成,此函数不再需要加载 JSON。"""
    logger.debug("api_keys load skipped — using SQLite persistence")


async def count() -> int:
    db = get_db()
    cursor = await db.execute("SELECT COUNT(*) AS cnt FROM api_keys")
    row = await cursor.fetchone()
    await cursor.close()
    return row["cnt"]


async def count_by_user(user_id: str) -> int:
    db = get_db()
    cursor = await db.execute(
        "SELECT COUNT(*) AS cnt FROM api_keys WHERE user_id = ?", (user_id,)
    )
    row = await cursor.fetchone()
    await cursor.close()
    return row["cnt"]


async def list_all() -> list[ApiKeyConfig]:
    db = get_db()
    cursor = await db.execute("SELECT * FROM api_keys ORDER BY created_at ASC")
    rows = await cursor.fetchall()
    await cursor.close()
    return [_row_to_api_key_config(r) for r in rows]


async def list_by_user(user_id: str) -> list[ApiKeyConfig]:
    db = get_db()
    cursor = await db.execute(
        "SELECT * FROM api_keys WHERE user_id = ? ORDER BY created_at ASC",
        (user_id,),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [_row_to_api_key_config(r) for r in rows]


async def get(key_id: str) -> ApiKeyConfig | None:
    db = get_db()
    cursor = await db.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,))
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        return None
    return _row_to_api_key_config(row)


async def get_by_key_hash(key_hash: str) -> ApiKeyConfig | None:
    db = get_db()
    cursor = await db.execute(
        "SELECT * FROM api_keys WHERE key_hash = ? AND status = 'active'",
        (key_hash,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        return None
    return _row_to_api_key_config(row)


async def create(key_config: ApiKeyConfig) -> ApiKeyConfig:
    db = get_db()
    async with _lock:
        # 查重
        cursor = await db.execute(
            "SELECT 1 FROM api_keys WHERE id = ?", (key_config.id,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            raise ValueError("api_key id already exists")

        created_at = (
            key_config.created_at.isoformat()
            if key_config.created_at.tzinfo
            else key_config.created_at.replace(tzinfo=timezone.utc).isoformat()
        )
        updated_at = (
            key_config.updated_at.isoformat()
            if key_config.updated_at.tzinfo
            else key_config.updated_at.replace(tzinfo=timezone.utc).isoformat()
        )
        expires_at = (
            key_config.expires_at.isoformat()
            if key_config.expires_at
            else None
        )

        await db.execute(
            "INSERT INTO api_keys "
            "(id, user_id, key_hash, key_prefix, key_masked, key_encrypted, name, models, "
            "quota, used_quota, status, is_default, expires_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                key_config.id,
                key_config.user_id,
                key_config.key_hash,
                key_config.key_prefix,
                key_config.key_masked,
                key_config.key_encrypted,
                key_config.name,
                json.dumps(key_config.models, ensure_ascii=False),
                key_config.quota,
                key_config.used_quota,
                key_config.status,
                int(key_config.is_default),
                expires_at,
                created_at,
                updated_at,
            ),
        )
        await db.commit()

    return key_config


async def update(key_id: str, **fields) -> ApiKeyConfig | None:
    """按字段更新 api_keys。fields 仅包含需要修改的列。"""
    if not fields:
        existing = await get(key_id)
        return existing

    db = get_db()
    now = _now_iso()

    # 构建 SET 子句
    set_parts: list[str] = []
    params: list = []

    for key, value in fields.items():
        if key == "models":
            set_parts.append("models = ?")
            params.append(json.dumps(value, ensure_ascii=False))
        elif key == "expires_at":
            set_parts.append("expires_at = ?")
            params.append(value.isoformat() if value else None)
        elif key in (
            "name", "quota", "used_quota", "status",
            "key_hash", "key_prefix", "key_masked",
        ):
            set_parts.append(f"{key} = ?")
            params.append(value)
        else:
            logger.warning("api_key update: unknown field=%s ignored", key)

    set_parts.append("updated_at = ?")
    params.append(now)
    params.append(key_id)

    async with _lock:
        cursor = await db.execute(
            f"UPDATE api_keys SET {', '.join(set_parts)} WHERE id = ?",
            params,
        )
        await db.commit()
        if cursor.rowcount == 0:
            return None

    return await get(key_id)


async def update_status(key_id: str, status: str) -> ApiKeyConfig | None:
    now = _now_iso()
    db = get_db()
    async with _lock:
        cursor = await db.execute(
            "UPDATE api_keys SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, key_id),
        )
        await db.commit()
        if cursor.rowcount == 0:
            return None

    return await get(key_id)


async def delete(key_id: str) -> bool:
    db = get_db()
    async with _lock:
        cursor = await db.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
        await db.commit()
        return cursor.rowcount > 0


async def increment_used_quota(key_id: str, amount: int = 1) -> None:
    now = _now_iso()
    db = get_db()
    async with _lock:
        await db.execute(
            "UPDATE api_keys SET used_quota = used_quota + ?, updated_at = ? "
            "WHERE id = ?",
            (amount, now, key_id),
        )
        await db.commit()
