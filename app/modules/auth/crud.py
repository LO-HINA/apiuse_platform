"""用户 CRUD —— 转发到 storage.user_repo,密码哈希在本层做。"""
from __future__ import annotations

from app.core.security import hash_password, verify_password
from app.storage import UserRecord, user_repo


async def get(user_id: str) -> UserRecord | None:
    return await user_repo.get(user_id)


async def get_by_username(username: str) -> UserRecord | None:
    return await user_repo.get_by_username(username)


async def create_user(
    *,
    username: str,
    password: str,
    display_name: str | None = None,
    role: str = "user",
) -> UserRecord:
    """username 冲突抛 ValueError,路由层翻成 409。"""
    return await user_repo.create(
        username=username,
        password_hash=hash_password(password),
        display_name=display_name,
        role=role,
    )


async def authenticate(*, username: str, password: str) -> UserRecord | None:
    """成败两态,不区分原因防枚举。"""
    user = await get_by_username(username)
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    if user.status != "active":
        return None
    return user
