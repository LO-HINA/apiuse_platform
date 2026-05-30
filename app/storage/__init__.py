"""内存仓库 + json 持久化层。

替代原 SQLAlchemy ORM/CRUD,职责保持一致:纯数据读写。
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
