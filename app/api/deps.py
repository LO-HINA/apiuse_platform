"""FastAPI 依赖集中点。

路由统一从这里 import 依赖,未来要换实现只改这一处。
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import InvalidTokenError, decode_access_token
from app.modules.api_keys.schemas import ApiKeyConfig
from app.modules.auth import crud as auth_crud
from app.storage import UserRecord

logger = logging.getLogger(__name__)


# auto_error=False: 头部缺失不立刻 401,把决定权交给依赖函数自己,
# 同一组工具能拼出"必须登录"和"可选登录"两种语义。
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# 公开路径白名单:使用 get_authenticated_user 时跳过认证
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


# ---------------------------------------------------------------------------
# API Key 鉴权依赖(供 /v1/* 路由使用)
# ---------------------------------------------------------------------------

_api_key_bearer = HTTPBearer(auto_error=False)


async def verify_api_key_dep(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_api_key_bearer)],
) -> ApiKeyConfig:
    """从 Authorization: Bearer sk-xxx 提取 key 并校验。

    校验通过返回 ApiKeyConfig,失败直接抛 401。
    路由层用 ``Depends(verify_api_key_dep)`` 即可。
    """
    from app.modules.api_keys import service as api_keys_service

    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的 API Key",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise exc

    raw_key = credentials.credentials
    if not raw_key or not raw_key.startswith("sk-"):
        raise exc

    key_config = await api_keys_service.verify_key(raw_key)
    if key_config is None:
        logger.warning("api_key auth failed: unknown key prefix=%s", raw_key[:8])
        raise exc

    if key_config.status != "active":
        logger.warning("api_key auth failed: key=%s status=%s", key_config.id, key_config.status)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API Key 已禁用",
        )

    logger.info("api_key auth ok: key=%s user=%s", key_config.id, key_config.user_id)
    return key_config


# ---------------------------------------------------------------------------
# 统一认证依赖
# ---------------------------------------------------------------------------


async def get_authenticated_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> UserRecord:
    """统一认证依赖,根据请求路径自动分流。

    - 公开路径白名单 → 跳过认证
    - /api/* 非白名单 → JWT 验证
    - /v1/* → API Key 验证,通过后返回对应的 UserRecord
    """
    path = request.url.path

    # 公开路径跳过认证
    if path in PUBLIC_PATHS:
        return _public_user()

    # /v1/* 路径:API Key 鉴权
    if path.startswith("/v1/"):
        from app.modules.api_keys import service as api_keys_service
        from fastapi.security import HTTPBearer

        cred_scheme = HTTPBearer(auto_error=False)
        cred = await cred_scheme(request)

        if cred is None or not cred.credentials or not cred.credentials.startswith("sk-"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的 API Key",
                headers={"WWW-Authenticate": "Bearer"},
            )

        key_config = await api_keys_service.verify_key(cred.credentials)
        if key_config is None:
            logger.warning("api_key auth via g_a_u failed: unknown key prefix=%s", cred.credentials[:8])
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的 API Key",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if key_config.status != "active":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="API Key 已禁用",
            )

        user = await auth_crud.get(key_config.user_id)
        if user is None or user.status != "active":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="关联用户不可用",
                headers={"WWW-Authenticate": "Bearer"},
            )
        logger.info("api_key auth via g_a_u ok: key=%s user=%s", key_config.id, user.id)
        return user

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
    "verify_api_key_dep",
]
