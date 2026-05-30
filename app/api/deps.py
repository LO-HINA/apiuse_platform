"""FastAPI 依赖集中点。

路由统一从这里 import 依赖,未来要换实现只改这一处。
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.core.security import InvalidTokenError, decode_access_token
from app.modules.auth import crud as auth_crud
from app.storage import UserRecord


# auto_error=False: 头部缺失不立刻 401,把决定权交给依赖函数自己,
# 同一组工具能拼出"必须登录"和"可选登录"两种语义。
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


async def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> UserRecord:
    """强制登录:无 token / token 错 / 用户不可用 → 401。"""
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
    current_user: Annotated[UserRecord, Depends(get_current_user)],
) -> UserRecord:
    """管理员守卫,留给后续 /api/admin/* 路由用。"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return current_user


__all__ = ["get_current_user", "get_optional_current_user", "get_admin_user"]
