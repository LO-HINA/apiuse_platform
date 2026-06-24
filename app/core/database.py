"""SQLite 数据库连接管理与建表。

单例连接,通过 get_db() 获取 aiosqlite.Connection。
init_db() 在 lifespan 启动阶段调用一次,建表并启用 WAL,
随后自动从旧 JSON 文件迁移历史用户数据(幂等)。

channel 静态信息走文件持久化(data/channels/auth/*.json),由
channels.crud 直接读写;运行时状态(success/failure/blacklist)走
channels_runtime 表。启动时会把旧 channels 表的 runtime 计数一次性
搬运到 channels_runtime(幂等),旧 channels 表留作孤儿表不再读写。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import aiosqlite

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
    """初始化数据库:创建连接、启用 WAL 与外键、建表、迁移旧数据。幂等,多次调用安全。"""
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

    # 从旧 users.json 迁移历史用户(幂等,已有数据不覆盖)
    await _migrate_json_data(_db)

    # 一次性把旧 channels 表的 runtime 计数搬到 channels_runtime(幂等)
    await _migrate_channels_runtime(_db)

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
    """从旧 JSON 文件迁移用户数据到 SQLite,幂等——已有记录跳过不覆盖。

    channel 静态信息已改走文件持久化(data/channels/auth/*.json),由
    channels.crud 直接读取;api_keys 早已落入 SQLite,不再从
    data/channels/keys/ 迁移。这里只保留 users.json → users 的迁移。
    """
    await _migrate_users(db)


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


async def _migrate_channels_runtime(db: aiosqlite.Connection) -> None:
    """一次性把旧 `channels` 表的 runtime 计数搬到 `channels_runtime`。

    channel 静态信息改走文件持久化后,旧 channels 表只剩 runtime 计数还有价值。
    这里把 success_count/failure_count/blacklisted_until 搬到新表,幂等
    (INSERT OR IGNORE)。旧 channels 表自身不删,留作孤儿表(不再读写)。

    全新 data.db(无旧 channels 表)时本函数为 no-op。
    """
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='channels'"
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        return

    cursor = await db.execute(
        "SELECT id, success_count, failure_count, blacklisted_until FROM channels"
    )
    rows = await cursor.fetchall()
    await cursor.close()
    for r in rows:
        await db.execute(
            "INSERT OR IGNORE INTO channels_runtime "
            "(channel_id, success_count, failure_count, blacklisted_until) "
            "VALUES (?, ?, ?, ?)",
            (r["id"], r["success_count"], r["failure_count"], r["blacklisted_until"]),
        )
    await db.commit()
    logger.info(
        "migrate channels_runtime: seeded %d rows from legacy channels table", len(rows)
    )


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

CREATE TABLE IF NOT EXISTS channels_runtime (
    channel_id TEXT PRIMARY KEY,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    blacklisted_until TEXT
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
