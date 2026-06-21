"""SQLite 持久化仓库层。

职责保持一致:纯数据读写,对外暴露 dataclass 记录和模块级单例 repo。
"""
from app.storage.repos import (
    MessageRecord,
    SessionRecord,
    UserRecord,
    message_repo,
    session_repo,
    user_repo,
)

__all__ = [
    "MessageRecord",
    "SessionRecord",
    "UserRecord",
    "message_repo",
    "session_repo",
    "user_repo",
]
