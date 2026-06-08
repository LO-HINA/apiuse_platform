"""会话业务服务。

router 只负责 HTTP 语义,这里负责组合 sessions_crud + messages_crud。
M2 起这里还承接总会话 LRU/TTL 清理:清掉老会话的消息体,但保留会话元信息。
"""
from __future__ import annotations

import logging
from uuid import UUID

from app.core.config import settings
from app.modules.messages import crud as messages_crud
from app.modules.messages.schemas import Message, Role
from app.modules.sessions import crud as sessions_crud
from app.modules.sessions.schemas import (
    SessionCreatedResponse,
    SessionDetailResponse,
    SessionListResponse,
    SessionSummary,
)

logger = logging.getLogger(__name__)


def _user_id_or_none(user_id: str | None) -> str | None:
    return user_id or None


async def list_for_user(user_id: str, *, limit: int = 50) -> SessionListResponse:
    """列出当前用户最近会话。匿名用户没有可列的历史。"""
    sessions = await sessions_crud.list_by_user(user_id, limit=limit)
    logger.debug("session list: user_id=%s count=%d", user_id, len(sessions))
    return SessionListResponse(
        sessions=[
            SessionSummary(
                id=UUID(s.id),
                title=s.title,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in sessions
        ],
    )


async def create_for_user(user_id: str | None) -> SessionCreatedResponse:
    """创建会话。user_id=None 表示匿名会话,只能凭 session_id 继续访问。"""
    obj = await sessions_crud.create(user_id=_user_id_or_none(user_id))
    logger.info("session created: session_id=%s user_id=%s", obj.id, user_id)
    return SessionCreatedResponse(session_id=UUID(obj.id))


async def resolve_or_create_owned(
    *,
    session_id: UUID | None,
    user_id: str | None,
) -> UUID:
    """供 chat 等上层用例复用的会话所有权边界。

    None 表示新建;传入 session_id 时,不存在或不归当前用户都抛 LookupError。
    这个函数让 chat.service 不必直接依赖 sessions.crud 的内部判断。
    """
    normalized_user_id = _user_id_or_none(user_id)
    if session_id is None:
        obj = await sessions_crud.create(user_id=normalized_user_id)
        return UUID(obj.id)

    sid_str = str(session_id)
    obj = await sessions_crud.get(sid_str)
    if obj is None or obj.user_id != normalized_user_id:
        raise LookupError("session not found")
    return session_id


async def touch(session_id: UUID | str) -> None:
    """刷新会话访问时间,同时更新 M2 LRU 所需的 last_accessed_at。"""
    await sessions_crud.touch(str(session_id))


async def get_owned_detail(
    *,
    session_id: UUID,
    user_id: str | None,
) -> SessionDetailResponse:
    """读取会话详情。不存在或不归当前用户都抛 LookupError,由 router 翻 404。"""
    sid_str = str(session_id)
    obj = await sessions_crud.get(sid_str)
    normalized_user_id = _user_id_or_none(user_id)
    if obj is None or obj.user_id != normalized_user_id:
        raise LookupError("session not found")

    await touch(sid_str)
    rows = await messages_crud.list_by_session(sid_str)
    messages = [
        Message(role=Role(r.role), content=r.content, created_at=r.created_at)
        for r in rows
    ]
    logger.debug("session fetched: session_id=%s msg_count=%d", session_id, len(messages))
    return SessionDetailResponse(session_id=session_id, messages=messages)


async def delete_owned(*, session_id: UUID, user_id: str | None) -> bool:
    """幂等删除。不归你 / 不存在都返回 False,保持原 API 行为。"""
    sid_str = str(session_id)
    obj = await sessions_crud.get(sid_str)
    normalized_user_id = _user_id_or_none(user_id)
    if obj is None or obj.user_id != normalized_user_id:
        logger.info(
            "session delete miss: session_id=%s user_id=%s reason=%s",
            session_id, user_id, "not_found" if obj is None else "not_owner",
        )
        return False

    success = await sessions_crud.delete(sid_str)
    # 内存版没有 cascade,这里显式清理消息体,避免 MessageRepo 残留孤儿数据。
    await messages_crud.delete_by_session(sid_str)
    logger.info("session delete: session_id=%s success=%s", session_id, success)
    return success


async def cleanup_inactive_message_bodies() -> int:
    """按 M2 LRU/TTL 策略清空老会话消息体,保留 session 元信息。

    触发方式保持轻量:聊天请求结束时调用一次。当前项目没有后台任务系统,
    不为这个学习阶段额外引入 scheduler/worker。
    """
    candidate_ids = await sessions_crud.cleanup_candidate_ids(
        max_active_sessions=settings.MAX_ACTIVE_SESSIONS,
        idle_ttl_minutes=settings.SESSION_IDLE_TTL_MINUTES,
    )
    deleted_total = 0
    for session_id in candidate_ids:
        deleted_total += await messages_crud.delete_by_session(session_id)

    if deleted_total:
        logger.info(
            "session cleanup: candidates=%d deleted_messages=%d",
            len(candidate_ids), deleted_total,
        )
    return deleted_total
