"""FastAPI 应用入口:创建 app、挂载路由 / 静态资源、生命周期。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import close_db, init_db
from app.core.exceptions import register_exception_handlers
from app.core.log_config import setup_logging
from app.core.middleware import RequestIDMiddleware
from app.modules.adapter.base import register_adapter
from app.modules.adapter.openai_compat_adapter import OpenAICompatAdapter
from app.modules.adapter.service import set_http_client
from app.modules.api_keys.router import router as api_keys_admin_router
from app.modules.api_keys.router import user_router as api_keys_user_router
from app.modules.auth.router import router as auth_router
from app.modules.channels import crud as channels_crud
from app.modules.channels.router import public_router as channels_public_router
from app.modules.channels.router import router as channels_router
from app.modules.chat.router import router as chat_router
from app.modules.chat.schemas import HealthResponse
from app.modules.relay.router import router as relay_router
from app.modules.sessions.router import router as sessions_router
from app.modules.usage.router import router as usage_router

# 日志要在 app 创建前 setup,启动期日志才会按统一格式输出
setup_logging()
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
INDEX_FILE = STATIC_DIR / "pages" / "chat" / "index.html"
CHANNELS_ACCOUNTS_FILE = STATIC_DIR / "pages" / "channels_accounts" / "index.html"
CHANNELS_KEYS_FILE = STATIC_DIR / "pages" / "channels_keys" / "index.html"
CHANNELS_USAGE_FILE = STATIC_DIR / "pages" / "channels_usage" / "index.html"
AUTH_FILE = STATIC_DIR / "pages" / "auth" / "index.html"


# ----------------------------------------------------------------------
# 生命周期
# ----------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ===== 启动 =====
    logger.info(
        "app starting up: name=%s env=%s use_fake_ai=%s",
        settings.PROJECT_NAME, settings.ENV, settings.USE_FAKE_AI,
    )

    # 初始化 SQLite 数据库(建表 + WAL + 外键)
    await init_db()

    if not settings.USE_FAKE_AI and await channels_crud.count() == 0:
        logger.warning(
            "channel 池为空,已自动降级到 fake AI 模式。"
            "通过管理后台添加 channel 后即可切回真实上游。"
        )

    # 为所有已有用户补建默认 API Key（幂等）
    await _ensure_default_keys_for_all_users()

    # 全应用共享一个 httpx.AsyncClient 才能复用连接池
    http_client = httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT)
    set_http_client(http_client)
    logger.info("httpx.AsyncClient initialized")

    yield

    # ===== 关闭 =====
    logger.info("app shutting down")
    await http_client.aclose()
    set_http_client(None)
    await close_db()
    logger.info("httpx.AsyncClient closed, database closed")


# ----------------------------------------------------------------------
# App 装配
# ----------------------------------------------------------------------

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="OpenAI 兼容协议的简化号池中转平台",
    version="0.1.0",
    lifespan=lifespan,
)

# 注册 Provider Adapter（模块级，import 即生效）
register_adapter(OpenAICompatAdapter())

# 中间件后注册的在外层、先执行;RequestID 要最先跑,所以最后注册
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOW_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestIDMiddleware)

register_exception_handlers(app)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(auth_router)
app.include_router(sessions_router)
app.include_router(chat_router)
app.include_router(relay_router)
app.include_router(channels_public_router)
app.include_router(channels_router)
app.include_router(api_keys_admin_router)
app.include_router(api_keys_user_router)
app.include_router(usage_router)


# ----------------------------------------------------------------------
# 首页 / 健康检查
# ----------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(INDEX_FILE)


@app.get("/channels", include_in_schema=False)
async def channels_redirect():
    return RedirectResponse(url="/channels/accounts", status_code=302)


@app.get("/channels/accounts", include_in_schema=False)
async def channels_accounts_page():
    return FileResponse(CHANNELS_ACCOUNTS_FILE)


@app.get("/channels/keys", include_in_schema=False)
async def channels_keys_page():
    return FileResponse(CHANNELS_KEYS_FILE)


@app.get("/channels/usage", include_in_schema=False)
async def channels_usage_page():
    return FileResponse(CHANNELS_USAGE_FILE)


@app.get("/login", include_in_schema=False)
@app.get("/register", include_in_schema=False)
async def auth_page():
    return FileResponse(AUTH_FILE)


async def _ensure_default_keys_for_all_users() -> None:
    """启动时为所有已有用户补建默认 API Key（幂等）。"""
    from app.core.database import get_db
    from app.modules.api_keys.service import ensure_default_key

    db = get_db()
    cursor = await db.execute("SELECT id FROM users")
    rows = await cursor.fetchall()
    await cursor.close()
    for row in rows:
        await ensure_default_key(row["id"])
    logger.info("default keys ensured for %d users", len(rows))


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="ok",
        message=f"{settings.PROJECT_NAME} is running",
    )


logger.info("app initialized: title=%s version=%s", app.title, app.version)
