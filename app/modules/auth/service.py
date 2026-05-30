"""鉴权业务服务:发 token 这步抽到这里,router 只管 HTTP 协议。"""
from __future__ import annotations

from app.core.config import settings
from app.core.security import create_access_token
from app.modules.auth.schemas import TokenResponse
from app.storage import UserRecord


def issue_token(user: UserRecord) -> TokenResponse:
    """签 JWT 并包成响应,role 进 claim 给前端 / admin 路由用。"""
    token = create_access_token(
        subject=user.id,
        extra_claims={"username": user.username, "role": user.role},
    )
    return TokenResponse(
        access_token=token,
        expires_in=settings.JWT_EXPIRE_MINUTES * 60,
    )
