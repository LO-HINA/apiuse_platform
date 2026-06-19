"""鉴权路由: register / login / me。

错误文案统一不区分原因,防枚举。
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.modules.auth.schemas import (
    AuthStatusResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.modules.auth import service as auth_service
from app.storage import UserRecord, user_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status() -> AuthStatusResponse:
    """公开端点,返回系统是否存在用户。"""
    count = await user_repo.count()
    return AuthStatusResponse(has_users=count > 0)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest) -> TokenResponse:
    """注册新用户,成功直接返回 token。"""
    try:
        token = await auth_service.register_user(
            username=payload.username,
            password=payload.password.get_secret_value(),
            display_name=payload.display_name,
        )
    except ValueError:
        # user_repo.create 在 username 重复时抛 ValueError
        logger.info("register conflict: username=%s", payload.username)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已被占用",
        )

    logger.info("user registered: username=%s", payload.username)
    return token


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest) -> TokenResponse:
    """用户名 + 密码登录,失败统一 401。"""
    token = await auth_service.login_user(
        username=payload.username,
        password=payload.password.get_secret_value(),
    )
    if token is None:
        logger.info("login failed: username=%s", payload.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.info("user logged in: username=%s", payload.username)
    return token


@router.get("/me", response_model=UserResponse)
async def me(
    current_user: Annotated[UserRecord, Depends(get_current_user)],
) -> UserResponse:
    """返回当前登录用户信息。"""
    return UserResponse.model_validate(current_user)
