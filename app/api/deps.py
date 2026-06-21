"""FastAPI 依赖集中点。

路由统一从这里 import 依赖,未来要换实现只改这一处。
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

from app.core.security import InvalidTokenError, decode_access_token
from app.modules.auth import crud as auth_crud
from app.storage import UserRecord


# auto_error=False: 头部缺失不立刻 401,把决定权交给依赖函数自己,
# 同一组工具能拼出"必须登录"和"可选登录"两种语义。
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# 公开路径白名单:使用 get_authenticated_user 时跳过认证
# /v1/* 暂未实现,命中后统一返回 501
PUBLIC_PATHS = frozenset({
    "/api/auth/status",
    "/api/auth/register",
    "/api/auth/login",
    "/api/channels/models",
    "/health",
})


def _public_user() -> UserRecord:
    """返回一个公开访问用的最小 UserRecord。"""
    return UserRecord(
        id="",
        username="",
        role="public",
        status="active",
    )


async def get_authenticated_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> UserRecord:
    """统一认证依赖,根据请求路径自动分流。

    - 公开路径白名单 → 跳过认证
    - /api/* 非白名单 → JWT 验证
    - /v1/* → API Key 验证(预留,当前返回 501)
    """
    path = request.url.path

    # 公开路径跳过认证
    if path in PUBLIC_PATHS:
        return _public_user()

    # /v1/* 路径:API Key 鉴权(预留)
    if path.startswith("/v1/"):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="API Key authentication not yet implemented",
        )

    # 默认:JWT 认证
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未登录或登录已失效",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exc
    try:
        payload = decode_access_token(token)
    except InvalidTokenError:
        raise credentials_exc

    user = await auth_crud.get(payload["sub"])
    if user is None or user.status != "active":
        raise credentials_exc
    return user


async def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> UserRecord:
    """强制登录:无 token / token 错 / 用户不可用 → 401。

    向后兼容封装,新代码请用 get_authenticated_user。
    """
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未登录或登录已失效",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exc

    try:
        payload = decode_access_token(token)
    except InvalidTokenError:
        raise credentials_exc

    user = await auth_crud.get(payload["sub"])
    if user is None or user.status != "active":
        raise credentials_exc
    return user


async def get_optional_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> UserRecord | None:
    """可选登录:无 token → None;带了就必须有效。"""
    if not token:
        return None
    try:
        payload = decode_access_token(token)
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已失效,请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await auth_crud.get(payload["sub"])
    if user is None or user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账号不可用",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_admin_user(
    current_user: Annotated[UserRecord, Depends(get_authenticated_user)],
) -> UserRecord:
    """管理员守卫:先认证再校验 role==admin。"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return current_user


__all__ = [
    "get_authenticated_user",
    "get_current_user",
    "get_optional_current_user",
    "get_admin_user",
]
