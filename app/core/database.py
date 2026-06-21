"""SQLite 数据库连接管理与建表。

单例连接,通过 get_db() 获取 aiosqlite.Connection。
init_db() 在 lifespan 启动阶段调用一次,建表并启用 WAL。
"""
from __future__ import annotations

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
    """初始化数据库:创建连接、启用 WAL 与外键、建表。幂等,多次调用安全。"""
    global _db

    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    _db = await aiosqlite.connect(str(_DB_FILE))
    _db.row_factory = aiosqlite.Row

    await _db.execute("PRAGMA journal_mode = WAL")
    await _db.execute("PRAGMA foreign_keys = ON")

    await _db.executescript(_SCHEMA_SQL)
    await _db.commit()

    logger.info("database initialized: file=%s", _DB_FILE)


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
    key_encrypted TEXT,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""
