"""FastAPI 应用入口:创建 app、挂载路由 / 静态资源、生命周期。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.log_config import setup_logging
from app.core.middleware import RequestIDMiddleware
from app.modules.ai_providers.service import set_http_client
from app.modules.auth.router import router as auth_router
from app.modules.channels import crud as channels_crud
from app.modules.channels.router import public_router as channels_public_router
from app.modules.channels.router import router as channels_router
from app.modules.channels.service import load_channels
from app.modules.chat.router import router as chat_router
from app.modules.chat.schemas import HealthResponse
from app.modules.sessions.router import router as sessions_router
from app.storage import user_repo

# 日志要在 app 创建前 setup,启动期日志才会按统一格式输出
setup_logging()
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
INDEX_FILE = STATIC_DIR / "pages" / "chat" / "index.html"
CHANNELS_FILE = STATIC_DIR / "pages" / "channels" / "index.html"
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

    # users.json 同步加载到内存
    user_repo.load()
    # M2 channel 池同样在启动期加载。缺少 channels.json 不阻塞启动,
    # 只有 USE_FAKE_AI=false 且真实调用进来时才会返回"无可用 channel"。
    load_channels()
    if not settings.USE_FAKE_AI and channels_crud.count() == 0:
        logger.warning(
            "channel 池为空(未配置 data/channels.json),"
            "已自动降级到 fake AI 模式。配置 channels.json 后重启即可切回真实上游。"
        )

    # 全应用共享一个 httpx.AsyncClient 才能复用连接池
    http_client = httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT)
    set_http_client(http_client)
    logger.info("httpx.AsyncClient initialized")

    yield

    # ===== 关闭 =====
    logger.info("app shutting down")
    await http_client.aclose()
    set_http_client(None)
    logger.info("httpx.AsyncClient closed")


# ----------------------------------------------------------------------
# App 装配
# ----------------------------------------------------------------------

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="OpenAI 兼容协议的简化号池中转平台",
    version="0.1.0",
    lifespan=lifespan,
)

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
app.include_router(channels_public_router)
app.include_router(channels_router)


# ----------------------------------------------------------------------
# 首页 / 健康检查
# ----------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(INDEX_FILE)


@app.get("/channels", include_in_schema=False)
async def channels_page():
    return FileResponse(CHANNELS_FILE)


@app.get("/login", include_in_schema=False)
@app.get("/register", include_in_schema=False)
async def auth_page():
    return FileResponse(AUTH_FILE)


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="ok",
        message=f"{settings.PROJECT_NAME} is running",
    )


logger.info("app initialized: title=%s version=%s", app.title, app.version)
