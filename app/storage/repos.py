"""内存仓库实现。

设计:
- SessionRepo / MessageRepo: 纯内存,重启清空
- UserRepo: 启动加载 users.json,写操作同步刷盘
- 仓库都是模块级单例,通过 ``from app.storage import xxx_repo`` 取用
- 用 asyncio.Lock 保护写操作,SSE 长流期间不阻塞读

dataclass 选用理由:轻量,字段固定,序列化成 dict 一行 ``asdict()`` 搞定。
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
    # M2 LRU/TTL 使用 last_accessed_at 判断"这个会话的消息体还能不能留在内存"。
    # updated_at 代表元信息更新时间,last_accessed_at 代表用户最近真正访问/对话时间。
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
    role: str = "user"  # "admin" 或 "user"
    status: str = "active"
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)


# ----------------------------------------------------------------------
# Session / Message 内存仓库 (重启清空)
# ----------------------------------------------------------------------

class SessionRepo:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}
        self._lock = asyncio.Lock()

    async def create(self, *, title: Optional[str] = None, user_id: Optional[str] = None) -> SessionRecord:
        async with self._lock:
            rec = SessionRecord(title=title, user_id=user_id)
            self._sessions[rec.id] = rec
            return rec

    async def get(self, session_id: str) -> Optional[SessionRecord]:
        return self._sessions.get(session_id)

    async def exists(self, session_id: str) -> bool:
        return session_id in self._sessions

    async def delete(self, session_id: str) -> bool:
        async with self._lock:
            return self._sessions.pop(session_id, None) is not None

    async def touch(self, session_id: str) -> None:
        async with self._lock:
            rec = self._sessions.get(session_id)
            if rec is not None:
                now = _now()
                rec.updated_at = now
                rec.last_accessed_at = now

    async def list_by_user(self, user_id: str, *, limit: int = 50) -> list[SessionRecord]:
        if not user_id:
            raise ValueError("list_by_user requires a non-empty user_id")
        rows = [s for s in self._sessions.values() if s.user_id == user_id]
        rows.sort(key=lambda s: s.updated_at, reverse=True)
        return rows[:limit]

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
        rows = list(self._sessions.values())
        candidate_ids: list[str] = []
        seen: set[str] = set()

        if idle_ttl_minutes > 0:
            idle_before = _now() - timedelta(minutes=idle_ttl_minutes)
            for rec in rows:
                if rec.last_accessed_at < idle_before:
                    candidate_ids.append(rec.id)
                    seen.add(rec.id)

        if max_active_sessions > 0 and len(rows) > max_active_sessions:
            excess_count = len(rows) - max_active_sessions
            rows.sort(key=lambda s: s.last_accessed_at)
            for rec in rows[:excess_count]:
                if rec.id not in seen:
                    candidate_ids.append(rec.id)
                    seen.add(rec.id)

        return candidate_ids


class MessageRepo:
    """消息按 session_id 分桶存,id 全局自增。"""

    def __init__(self) -> None:
        self._by_session: dict[str, list[MessageRecord]] = {}
        self._next_id = 1
        self._lock = asyncio.Lock()

    async def add(self, *, session_id: str, role: str, content: str) -> MessageRecord:
        async with self._lock:
            rec = MessageRecord(
                id=self._next_id,
                session_id=session_id,
                role=role,
                content=content,
            )
            self._next_id += 1
            self._by_session.setdefault(session_id, []).append(rec)
            return rec

    async def list_by_session(self, session_id: str) -> list[MessageRecord]:
        return list(self._by_session.get(session_id, []))

    async def list_recent(self, session_id: str, *, limit: int) -> list[MessageRecord]:
        if limit <= 0:
            return []
        return list(self._by_session.get(session_id, []))[-limit:]

    async def delete_by_session(self, session_id: str) -> int:
        async with self._lock:
            rows = self._by_session.pop(session_id, [])
            return len(rows)

    async def trim(self, session_id: str, max_keep: int) -> int:
        """超出 max_keep 时丢掉最早的,返回实际删除条数。"""
        if max_keep <= 0:
            return 0
        async with self._lock:
            rows = self._by_session.get(session_id)
            if not rows or len(rows) <= max_keep:
                return 0
            drop = len(rows) - max_keep
            del rows[:drop]
            return drop


# ----------------------------------------------------------------------
# User 仓库 (json 持久化)
# ----------------------------------------------------------------------

class UserRepo:
    """用户数据走 users.json,启动加载,写入即刷盘。"""

    def __init__(self, file_path: Path) -> None:
        self._file = file_path
        self._users: dict[str, UserRecord] = {}
        self._by_username: dict[str, str] = {}  # username -> id
        self._lock = asyncio.Lock()
        self._loaded = False

    def load(self) -> None:
        """同步加载,在 lifespan 启动阶段调一次。"""
        if self._loaded:
            return
        if not self._file.exists():
            self._loaded = True
            logger.info("users.json 不存在,以空用户表启动: %s", self._file)
            return
        raw = json.loads(self._file.read_text(encoding="utf-8"))
        for item in raw:
            rec = UserRecord(
                id=item["id"],
                username=item["username"],
                password_hash=item["password_hash"],
                display_name=item.get("display_name"),
                role=item.get("role", "user"),
                status=item.get("status", "active"),
                created_at=datetime.fromisoformat(item["created_at"]),
                updated_at=datetime.fromisoformat(item["updated_at"]),
            )
            self._users[rec.id] = rec
            self._by_username[rec.username] = rec.id
        self._loaded = True
        logger.info("users.json 加载完成: count=%d", len(self._users))

    def _flush(self) -> None:
        """原子写盘:先写 .tmp 再 rename,避免半截文件。"""
        self._file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._file.with_suffix(self._file.suffix + ".tmp")
        payload = []
        for rec in self._users.values():
            d = asdict(rec)
            d["created_at"] = rec.created_at.isoformat()
            d["updated_at"] = rec.updated_at.isoformat()
            payload.append(d)
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._file)

    async def get(self, user_id: str) -> Optional[UserRecord]:
        return self._users.get(user_id)

    async def count(self) -> int:
        return len(self._users)

    async def get_by_username(self, username: str) -> Optional[UserRecord]:
        uid = self._by_username.get(username)
        return self._users.get(uid) if uid else None

    async def create(
        self,
        *,
        username: str,
        password_hash: str,
        display_name: Optional[str] = None,
        role: str = "user",
    ) -> UserRecord:
        async with self._lock:
            if username in self._by_username:
                raise ValueError("username already exists")
            rec = UserRecord(
                username=username,
                password_hash=password_hash,
                display_name=display_name,
                role=role,
            )
            self._users[rec.id] = rec
            self._by_username[username] = rec.id
            self._flush()
            return rec

    async def update_role(self, user_id: str, role: str) -> Optional[UserRecord]:
        async with self._lock:
            rec = self._users.get(user_id)
            if rec is None:
                return None
            rec.role = role
            rec.updated_at = _now()
            self._flush()
            return rec


# ----------------------------------------------------------------------
# 单例
# ----------------------------------------------------------------------

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"

session_repo = SessionRepo()
message_repo = MessageRepo()
user_repo = UserRepo(_DATA_DIR / "users.json")
