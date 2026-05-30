"""消息 CRUD —— 转发到 storage.message_repo。"""
from __future__ import annotations

from app.storage import MessageRecord, message_repo


async def add(*, session_id: str, role: str, content: str) -> MessageRecord:
    return await message_repo.add(session_id=session_id, role=role, content=content)


async def list_by_session(session_id: str) -> list[MessageRecord]:
    return await message_repo.list_by_session(session_id)


async def list_recent(session_id: str, *, limit: int) -> list[MessageRecord]:
    return await message_repo.list_recent(session_id, limit=limit)


async def trim_history(session_id: str, max_keep: int) -> int:
    return await message_repo.trim(session_id, max_keep)


async def delete_by_session(session_id: str) -> int:
    return await message_repo.delete_by_session(session_id)
