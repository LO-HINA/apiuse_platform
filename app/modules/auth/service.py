"""鉴权业务服务。

router 只管 HTTP 状态码和依赖注入,注册 / 登录的业务判断都收束到这里。
这样后续要加登录审计、限流、管理员创建用户时,不用让 router 继续变厚。
"""
from __future__ import annotations

from app.core.config import settings
from app.core.security import create_access_token
from app.modules.auth import crud as auth_crud
from app.modules.auth.schemas import TokenResponse
from app.storage import UserRecord, user_repo


async def register_user(
    *,
    username: str,
    password: str,
    display_name: str | None = None,
) -> TokenResponse:
    """创建用户并直接签发 token。

    系统无用户时自动设为 admin 角色。
    username 重复时 auth_crud 会抛 ValueError,router 负责翻成 409。
    """
    role = "admin" if await user_repo.count() == 0 else "user"
    user = await auth_crud.create_user(
        username=username,
        password=password,
        display_name=display_name,
        role=role,
    )

    # 为新用户自动创建 Web 端默认 API Key
    from app.modules.api_keys.service import ensure_default_key
    await ensure_default_key(user.id)

    return issue_token(user)


async def login_user(*, username: str, password: str) -> TokenResponse | None:
    """登录成功返回 token,失败返回 None。

    失败原因不向外拆分,避免用户名枚举和账号状态探测。
    """
    user = await auth_crud.authenticate(username=username, password=password)
    if user is None:
        return None
    return issue_token(user)


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
