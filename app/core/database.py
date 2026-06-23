"""SQLite 数据库连接管理与建表。

单例连接,通过 get_db() 获取 aiosqlite.Connection。
init_db() 在 lifespan 启动阶段调用一次,建表并启用 WAL,
随后自动从旧 JSON 文件迁移历史数据(幂等)。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import aiosqlite

from app.core.crypto import encrypt

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_DB_FILE = _DATA_DIR / "data.db"

_db: aiosqlite.Connection | None = None


def get_db() -> aiosqlite.Connection:
    """返回模块级单例数据库连接。必须先调用 init_db()。"""
    if _db is None:
        raise RuntimeError("database not initialized; call init_db() during startup")
    return _db


async def init_db() -> None:
    """初始化数据库:创建连接、启用 WAL 与外键、建表、迁移旧 JSON 数据。幂等,多次调用安全。"""
    global _db

    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    _db = await aiosqlite.connect(str(_DB_FILE))
    _db.row_factory = aiosqlite.Row

    await _db.execute("PRAGMA journal_mode = WAL")
    await _db.execute("PRAGMA foreign_keys = ON")

    await _db.executescript(_SCHEMA_SQL)
    await _db.commit()

    # 迁移：为已有 api_keys 表补加 is_default 列
    await _migrate_add_is_default(_db)

    # 从旧 JSON 文件迁移历史数据(幂等,已有数据不覆盖)
    await _migrate_json_data(_db)

    logger.info("database initialized: file=%s", _DB_FILE)


# ---------------------------------------------------------------------------
# 旧 JSON → SQLite 数据迁移
# ---------------------------------------------------------------------------

async def _migrate_add_is_default(db: aiosqlite.Connection) -> None:
    """为已有 api_keys 表补加 is_default 列，幂等。"""
    try:
        await db.execute("ALTER TABLE api_keys ADD COLUMN is_default INTEGER NOT NULL DEFAULT 0")
        await db.commit()
        logger.info("migrate: added is_default column to api_keys")
    except aiosqlite.OperationalError:
        pass  # 列已存在


async def _migrate_json_data(db: aiosqlite.Connection) -> None:
    """从旧 JSON 文件迁移数据到 SQLite,幂等——已有记录跳过不覆盖。"""
    await _migrate_users(db)
    await _migrate_channels(db)
    await _migrate_api_keys(db)


async def _migrate_users(db: aiosqlite.Connection) -> None:
    """从 data/users.json 迁移用户。按 username 和 id 判重。"""
    users_file = _DATA_DIR / "users.json"
    if not users_file.exists():
        return

    users_data: list[dict] = json.loads(users_file.read_text(encoding="utf-8"))
    for user in users_data:
        uid = user["id"]
        username = user["username"]

        # 检查 username 是否已存在
        cursor = await db.execute("SELECT id FROM users WHERE username = ?", (username,))
        if await cursor.fetchone():
            await cursor.close()
            logger.info("migrate users: skip existing username=%s", username)
            continue
        await cursor.close()

        # 检查 id 是否已存在
        cursor = await db.execute("SELECT id FROM users WHERE id = ?", (uid,))
        if await cursor.fetchone():
            await cursor.close()
            logger.info("migrate users: skip existing id=%s", uid)
            continue
        await cursor.close()

        await db.execute(
            """INSERT INTO users (id, username, password_hash, display_name,
               role, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                uid,
                username,
                user["password_hash"],
                user.get("display_name"),
                user.get("role", "user"),
                user.get("status", "active"),
                user["created_at"],
                user["updated_at"],
            ),
        )
        logger.info("migrate users: inserted username=%s id=%s", username, uid)

    await db.commit()
    logger.info("migrate users: done")


async def _migrate_channels(db: aiosqlite.Connection) -> None:
    """从 data/channels/auth/*.json 迁移 channel。按 id 判重, api_key 经 Fernet 加密。"""
    auth_dir = _DATA_DIR / "channels" / "auth"
    if not auth_dir.exists():
        return

    for json_file in sorted(auth_dir.glob("*.json")):
        ch: dict = json.loads(json_file.read_text(encoding="utf-8"))
        ch_id = ch["id"]

        cursor = await db.execute("SELECT id FROM channels WHERE id = ?", (ch_id,))
        if await cursor.fetchone():
            await cursor.close()
            logger.info("migrate channels: skip existing id=%s", ch_id)
            continue
        await cursor.close()

        # 加密 API key
        raw_key: str = ch.get("key") or ""
        encrypted_key = encrypt(raw_key) if raw_key else ""

        # JSON 序列化列表/字典字段
        models_json = json.dumps(ch.get("models", []))
        redirect_json = json.dumps(ch.get("model_redirect", {}))

        enabled = 1 if ch.get("enabled", True) else 0

        await db.execute(
            """INSERT INTO channels (id, name, provider_type, base_url, api_key,
               organization, "group", models, model_redirect, weight, enabled,
               success_count, failure_count, blacklisted_until, created_at,
               updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ch_id,
                ch.get("name", ""),
                ch.get("provider_type", "openai_compat"),
                ch.get("url", ""),
                encrypted_key,
                ch.get("organization"),
                ch.get("group", "default"),
                models_json,
                redirect_json,
                ch.get("weight", 1),
                enabled,
                ch.get("success_count", 0),
                ch.get("failure_count", 0),
                ch.get("blacklisted_until"),
                ch["created_at"],
                ch["updated_at"],
            ),
        )
        logger.info("migrate channels: inserted id=%s name=%s", ch_id, ch.get("name"))

    await db.commit()
    logger.info("migrate channels: done")


async def _migrate_api_keys(db: aiosqlite.Connection) -> None:
    """从 data/channels/keys/*.json 迁移 API key。按 id 和 key_hash 判重,验证 user_id 外键。"""
    keys_dir = _DATA_DIR / "channels" / "keys"
    if not keys_dir.exists():
        return

    for json_file in sorted(keys_dir.glob("*.json")):
        key_list: list[dict] = json.loads(json_file.read_text(encoding="utf-8"))
        for ak in key_list:
            key_id = ak["id"]
            key_hash = ak.get("key_hash", "")

            # 按 id 判重
            cursor = await db.execute("SELECT id FROM api_keys WHERE id = ?", (key_id,))
            if await cursor.fetchone():
                await cursor.close()
                logger.info("migrate api_keys: skip existing id=%s", key_id)
                continue
            await cursor.close()

            # 按 key_hash 判重
            if key_hash:
                cursor = await db.execute(
                    "SELECT id FROM api_keys WHERE key_hash = ?", (key_hash,)
                )
                if await cursor.fetchone():
                    await cursor.close()
                    logger.info(
                        "migrate api_keys: skip existing key_hash=%s...", key_hash[:12]
                    )
                    continue
                await cursor.close()

            # 验证关联的 user_id 是否存在
            user_id = ak.get("user_id", "")
            if user_id:
                cursor = await db.execute(
                    "SELECT id FROM users WHERE id = ?", (user_id,)
                )
                if not await cursor.fetchone():
                    await cursor.close()
                    logger.warning(
                        "migrate api_keys: skip id=%s — user_id=%s not found",
                        key_id,
                        user_id,
                    )
                    continue
                await cursor.close()

            models_json = json.dumps(ak.get("models", []))

            await db.execute(
                """INSERT INTO api_keys (id, user_id, key_hash, key_prefix,
                   key_masked, name, models, quota, used_quota, status,
                   key_encrypted, expires_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    key_id,
                    user_id,
                    key_hash,
                    ak.get("key_prefix", "sk-"),
                    ak.get("key_masked", ""),
                    ak.get("name", ""),
                    models_json,
                    ak.get("quota", 0),
                    ak.get("used_quota", 0),
                    ak.get("status", "active"),
                    None,  # key_encrypted — 旧 JSON 不含明文 key
                    ak.get("expires_at"),
                    ak["created_at"],
                    ak["updated_at"],
                ),
            )
            logger.info("migrate api_keys: inserted id=%s name=%s", key_id, ak.get("name"))

    await db.commit()
    logger.info("migrate api_keys: done")


async def close_db() -> None:
    """关闭数据库连接。"""
    global _db
    if _db is not None:
        await _db.close()
        _db = None
        logger.info("database closed")


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    role TEXT NOT NULL DEFAULT 'user',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    title TEXT,
    last_accessed_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channels (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    provider_type TEXT NOT NULL DEFAULT 'openai_compat',
    base_url TEXT NOT NULL DEFAULT '',
    api_key TEXT NOT NULL DEFAULT '',
    organization TEXT,
    "group" TEXT NOT NULL DEFAULT 'default',
    models TEXT NOT NULL DEFAULT '[]',
    model_redirect TEXT NOT NULL DEFAULT '{}',
    weight INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    blacklisted_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL DEFAULT 'sk-',
    key_masked TEXT NOT NULL,
    name TEXT NOT NULL,
    models TEXT NOT NULL DEFAULT '[]',
    quota INTEGER NOT NULL DEFAULT 0,
    used_quota INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    is_default INTEGER NOT NULL DEFAULT 0,
    key_encrypted TEXT,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS call_logs (
    id TEXT PRIMARY KEY,
    api_key_id TEXT NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    stream INTEGER NOT NULL DEFAULT 0,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""
