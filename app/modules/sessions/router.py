"""会话 CRUD 路由。"""
from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user, get_optional_current_user
from app.modules.sessions import service as sessions_service
from app.modules.sessions.schemas import (
    SessionCreatedResponse,
    SessionDeleteResponse,
    SessionDetailResponse,
    SessionListResponse,
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
    return await sessions_service.list_for_user(current_user.id, limit=50)


@router.post("/sessions", response_model=SessionCreatedResponse)
async def create_session(
    current_user: Annotated[UserRecord | None, Depends(get_optional_current_user)],
) -> SessionCreatedResponse:
    """匿名也允许,user_id=None 时只能凭 session_id 自己用。"""
    user_id = current_user.id if current_user else None
    return await sessions_service.create_for_user(user_id)


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_session(
    session_id: UUID,
    current_user: Annotated[UserRecord | None, Depends(get_optional_current_user)],
) -> SessionDetailResponse:
    """不存在 / 不归你 → 一律 404 防枚举。"""
    user_id = current_user.id if current_user else None
    try:
        return await sessions_service.get_owned_detail(session_id=session_id, user_id=user_id)
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="session not found",
        )


@router.delete("/sessions/{session_id}", response_model=SessionDeleteResponse)
async def delete_session(
    session_id: UUID,
    current_user: Annotated[UserRecord | None, Depends(get_optional_current_user)],
) -> SessionDeleteResponse:
    """幂等:不归你 / 不存在都返回 success=False,不抛 404。"""
    user_id = current_user.id if current_user else None
    success = await sessions_service.delete_owned(session_id=session_id, user_id=user_id)
    return SessionDeleteResponse(success=success)
