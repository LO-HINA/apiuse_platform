"""会话 CRUD 路由。"""
from __future__ import annotations

import logging
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user, get_optional_current_user
from app.modules.messages import crud as messages_crud
from app.modules.messages.schemas import Message, Role
from app.modules.sessions import crud as sessions_crud
from app.modules.sessions.schemas import (
    SessionCreatedResponse,
    SessionDeleteResponse,
    SessionDetailResponse,
    SessionListResponse,
    SessionSummary,
)
from app.storage import UserRecord

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["sessions"])


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    current_user: Annotated[UserRecord, Depends(get_current_user)],
) -> SessionListResponse:
    """列出当前用户最近的会话(最多 50 条,按 updated_at 倒序)。

    路径声明顺序要先于 /sessions/{session_id},否则 GET /api/sessions
    会被动态路由当成 session_id="sessions" 接走。
    """
    sessions = await sessions_crud.list_by_user(current_user.id, limit=50)
    logger.debug("session list: user_id=%s count=%d", current_user.id, len(sessions))
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


@router.post("/sessions", response_model=SessionCreatedResponse)
async def create_session(
    current_user: Annotated[Optional[UserRecord], Depends(get_optional_current_user)],
) -> SessionCreatedResponse:
    """匿名也允许,user_id=None 时只能凭 session_id 自己用。"""
    user_id = current_user.id if current_user else None
    obj = await sessions_crud.create(user_id=user_id)
    logger.info("session created: session_id=%s user_id=%s", obj.id, user_id)
    return SessionCreatedResponse(session_id=UUID(obj.id))


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_session(
    session_id: UUID,
    current_user: Annotated[Optional[UserRecord], Depends(get_optional_current_user)],
) -> SessionDetailResponse:
    """不存在 / 不归你 → 一律 404 防枚举。"""
    sid_str = str(session_id)
    obj = await sessions_crud.get(sid_str)
    user_id = current_user.id if current_user else None

    if obj is None or obj.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="session not found",
        )

    rows = await messages_crud.list_by_session(sid_str)
    messages = [
        Message(role=Role(r.role), content=r.content, created_at=r.created_at)
        for r in rows
    ]
    logger.debug("session fetched: session_id=%s msg_count=%d", session_id, len(messages))
    return SessionDetailResponse(session_id=session_id, messages=messages)


@router.delete("/sessions/{session_id}", response_model=SessionDeleteResponse)
async def delete_session(
    session_id: UUID,
    current_user: Annotated[Optional[UserRecord], Depends(get_optional_current_user)],
) -> SessionDeleteResponse:
    """幂等:不归你 / 不存在都返回 success=False,不抛 404。"""
    sid_str = str(session_id)
    obj = await sessions_crud.get(sid_str)
    user_id = current_user.id if current_user else None

    if obj is None or obj.user_id != user_id:
        logger.info(
            "session delete miss: session_id=%s user_id=%s reason=%s",
            session_id, user_id, "not_found" if obj is None else "not_owner",
        )
        return SessionDeleteResponse(success=False)

    success = await sessions_crud.delete(sid_str)
    # 内存版没有 cascade,顺手清掉这个会话的消息防止 message_repo 累积
    await messages_crud.delete_by_session(sid_str)
    logger.info("session delete: session_id=%s success=%s", session_id, success)
    return SessionDeleteResponse(success=success)
