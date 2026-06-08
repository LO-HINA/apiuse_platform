"""会话 CRUD —— 转发到 storage.session_repo。"""
from __future__ import annotations

from app.storage import SessionRecord, session_repo


async def create(*, title: str | None = None, user_id: str | None = None) -> SessionRecord:
    return await session_repo.create(title=title, user_id=user_id)


async def get(session_id: str) -> SessionRecord | None:
    return await session_repo.get(session_id)


async def exists(session_id: str) -> bool:
    return await session_repo.exists(session_id)


async def delete(session_id: str) -> bool:
    return await session_repo.delete(session_id)


async def touch(session_id: str) -> None:
    await session_repo.touch(session_id)


async def list_by_user(user_id: str, *, limit: int = 50) -> list[SessionRecord]:
    return await session_repo.list_by_user(user_id, limit=limit)


async def cleanup_candidate_ids(
    *,
    max_active_sessions: int,
    idle_ttl_minutes: int,
) -> list[str]:
    return await session_repo.cleanup_candidate_ids(
        max_active_sessions=max_active_sessions,
        idle_ttl_minutes=idle_ttl_minutes,
    )
