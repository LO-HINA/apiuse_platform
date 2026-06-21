"""SQLite 仓库实现。

设计:
- SessionRepo / MessageRepo / UserRepo 统一走 SQLite 持久化。
- 仓库都是模块级单例,通过 ``from app.storage import xxx_repo`` 取用。
- 用 asyncio.Lock 保护写操作,SSE 长流期间不阻塞读。
- 时间字段在 SQLite 存 ISO 8601 字符串,读回时转为 datetime 对象。
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.database import get_db

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_uuid() -> str:
    return str(uuid.uuid4())


# ----------------------------------------------------------------------
# 数据记录
# ----------------------------------------------------------------------

@dataclass
class SessionRecord:
    id: str = field(default_factory=_new_uuid)
    user_id: Optional[str] = None
    title: Optional[str] = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    last_accessed_at: datetime = field(default_factory=_now)


@dataclass
class MessageRecord:
    id: int = 0
    session_id: str = ""
    role: str = ""
    content: str = ""
    created_at: datetime = field(default_factory=_now)


@dataclass
class UserRecord:
    id: str = field(default_factory=_new_uuid)
    username: str = ""
    password_hash: str = ""
    display_name: Optional[str] = None
    role: str = "user"
    status: str = "active"
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)


# ----------------------------------------------------------------------
# 行 → 记录 转换
# ----------------------------------------------------------------------

def _row_to_user(row) -> UserRecord:
    return UserRecord(
        id=row["id"],
        username=row["username"],
        password_hash=row["password_hash"],
        display_name=row["display_name"],
        role=row["role"],
        status=row["status"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _row_to_session(row) -> SessionRecord:
    return SessionRecord(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        last_accessed_at=datetime.fromisoformat(row["last_accessed_at"]),
    )


def _row_to_message(row) -> MessageRecord:
    return MessageRecord(
        id=row["id"],
        session_id=row["session_id"],
        role=row["role"],
        content=row["content"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


# ----------------------------------------------------------------------
# Session 仓库
# ----------------------------------------------------------------------

class SessionRepo:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def create(
        self, *, title: Optional[str] = None, user_id: Optional[str] = None
    ) -> SessionRecord:
        now = _now_iso()
        rec_id = _new_uuid()
        db = get_db()
        async with self._lock:
            await db.execute(
                "INSERT INTO sessions (id, user_id, title, last_accessed_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (rec_id, user_id, title, now, now, now),
            )
            await db.commit()
        return SessionRecord(
            id=rec_id, user_id=user_id, title=title,
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
            last_accessed_at=datetime.fromisoformat(now),
        )

    async def get(self, session_id: str) -> Optional[SessionRecord]:
        db = get_db()
        cursor = await db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return _row_to_session(row)

    async def exists(self, session_id: str) -> bool:
        db = get_db()
        cursor = await db.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,))
        row = await cursor.fetchone()
        await cursor.close()
        return row is not None

    async def delete(self, session_id: str) -> bool:
        db = get_db()
        async with self._lock:
            cursor = await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            await db.commit()
            return cursor.rowcount > 0

    async def touch(self, session_id: str) -> None:
        now = _now_iso()
        db = get_db()
        async with self._lock:
            await db.execute(
                "UPDATE sessions SET updated_at = ?, last_accessed_at = ? WHERE id = ?",
                (now, now, session_id),
            )
            await db.commit()

    async def list_by_user(
        self, user_id: str, *, limit: int = 50
    ) -> list[SessionRecord]:
        if not user_id:
            raise ValueError("list_by_user requires a non-empty user_id")
        db = get_db()
        cursor = await db.execute(
            "SELECT * FROM sessions WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
            (user_id, limit),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [_row_to_session(r) for r in rows]

    async def cleanup_candidate_ids(
        self,
        *,
        max_active_sessions: int,
        idle_ttl_minutes: int,
    ) -> list[str]:
        """返回应清空消息体的 session_id,但不删除 session 元信息。

        两类会被选中:
        1. 闲置时间超过 TTL 的会话。
        2. 总会话数超过上限时,last_accessed_at 最老的一批会话。

        这里故意只返回 id,不碰 MessageRepo。storage 层保持原子仓库职责,
        真正"清消息体"由 sessions.service 组合 SessionRepo + MessageRepo 完成。
        """
        db = get_db()
        candidate_ids: list[str] = []
        seen: set[str] = set()

        if idle_ttl_minutes > 0:
            idle_before = (_now() - timedelta(minutes=idle_ttl_minutes)).isoformat()
            cursor = await db.execute(
                "SELECT id FROM sessions WHERE last_accessed_at < ?",
                (idle_before,),
            )
            rows = await cursor.fetchall()
            await cursor.close()
            for row in rows:
                candidate_ids.append(row["id"])
                seen.add(row["id"])

        if max_active_sessions > 0:
            cursor = await db.execute("SELECT COUNT(*) AS cnt FROM sessions")
            row = await cursor.fetchone()
            await cursor.close()
            total = row["cnt"]
            if total > max_active_sessions:
                excess = total - max_active_sessions
                cursor = await db.execute(
                    "SELECT id FROM sessions ORDER BY last_accessed_at ASC LIMIT ?",
                    (excess,),
                )
                rows = await cursor.fetchall()
                await cursor.close()
                for row in rows:
                    if row["id"] not in seen:
                        candidate_ids.append(row["id"])
                        seen.add(row["id"])

        return candidate_ids


# ----------------------------------------------------------------------
# Message 仓库
# ----------------------------------------------------------------------

class MessageRepo:
    """消息按 session_id 分桶存,id 用 SQLite AUTOINCREMENT。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def add(
        self, *, session_id: str, role: str, content: str
    ) -> MessageRecord:
        now = _now_iso()
        db = get_db()
        async with self._lock:
            cursor = await db.execute(
                "INSERT INTO messages (session_id, role, content, created_at) "
                "VALUES (?, ?, ?, ?)",
                (session_id, role, content, now),
            )
            await db.commit()
            msg_id = cursor.lastrowid
        return MessageRecord(
            id=msg_id,
            session_id=session_id,
            role=role,
            content=content,
            created_at=datetime.fromisoformat(now),
        )

    async def list_by_session(self, session_id: str) -> list[MessageRecord]:
        db = get_db()
        cursor = await db.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [_row_to_message(r) for r in rows]

    async def list_recent(
        self, session_id: str, *, limit: int
    ) -> list[MessageRecord]:
        if limit <= 0:
            return []
        db = get_db()
        cursor = await db.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        # 反转以保持时间升序(最早→最新)
        result = [_row_to_message(r) for r in reversed(rows)]
        return result

    async def delete_by_session(self, session_id: str) -> int:
        db = get_db()
        async with self._lock:
            cursor = await db.execute(
                "DELETE FROM messages WHERE session_id = ?", (session_id,)
            )
            await db.commit()
            return cursor.rowcount

    async def trim(self, session_id: str, max_keep: int) -> int:
        """超出 max_keep 时丢掉最早的,返回实际删除条数。"""
        if max_keep <= 0:
            return 0
        db = get_db()
        async with self._lock:
            cursor = await db.execute(
                "SELECT COUNT(*) AS cnt FROM messages WHERE session_id = ?",
                (session_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()
            total = row["cnt"]
            if total <= max_keep:
                return 0
            drop = total - max_keep
            cursor = await db.execute(
                "DELETE FROM messages WHERE id IN ("
                "SELECT id FROM messages WHERE session_id = ? ORDER BY id ASC LIMIT ?"
                ")",
                (session_id, drop),
            )
            await db.commit()
            return cursor.rowcount


# ----------------------------------------------------------------------
# User 仓库 (SQLite 持久化)
# ----------------------------------------------------------------------

class UserRepo:
    """用户数据走 SQLite 持久化。"""

    def __init__(self, file_path=None) -> None:  # noqa: ARG002 — 保持签名兼容
        self._lock = asyncio.Lock()

    async def get(self, user_id: str) -> Optional[UserRecord]:
        db = get_db()
        cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return _row_to_user(row)

    async def count(self) -> int:
        db = get_db()
        cursor = await db.execute("SELECT COUNT(*) AS cnt FROM users")
        row = await cursor.fetchone()
        await cursor.close()
        return row["cnt"]

    async def get_by_username(self, username: str) -> Optional[UserRecord]:
        db = get_db()
        cursor = await db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return _row_to_user(row)

    async def create(
        self,
        *,
        username: str,
        password_hash: str,
        display_name: Optional[str] = None,
        role: str = "user",
    ) -> UserRecord:
        db = get_db()
        now = _now_iso()
        user_id = _new_uuid()
        async with self._lock:
            # 先查重,避免依赖 UNIQUE 约束抛异常后还要解析 SQLite 错误码
            cursor = await db.execute(
                "SELECT 1 FROM users WHERE username = ?", (username,)
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row is not None:
                raise ValueError("username already exists")

            await db.execute(
                "INSERT INTO users (id, username, password_hash, display_name, role, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'active', ?, ?)",
                (user_id, username, password_hash, display_name, role, now, now),
            )
            await db.commit()

        return UserRecord(
            id=user_id,
            username=username,
            password_hash=password_hash,
            display_name=display_name,
            role=role,
            status="active",
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
        )

    async def update_role(
        self, user_id: str, role: str
    ) -> Optional[UserRecord]:
        now = _now_iso()
        db = get_db()
        async with self._lock:
            cursor = await db.execute(
                "UPDATE users SET role = ?, updated_at = ? WHERE id = ?",
                (role, now, user_id),
            )
            await db.commit()
            if cursor.rowcount == 0:
                return None

        return await self.get(user_id)


# ----------------------------------------------------------------------
# 单例
# ----------------------------------------------------------------------

session_repo = SessionRepo()
message_repo = MessageRepo()
# file_path 参数保留但不再使用,保持向后兼容
user_repo = UserRepo()
