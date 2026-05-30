"""
全局异常处理器。

设计目标:
- 统一错误响应结构: {"code": int, "message": str, "request_id": str}
  前端 / 客户端只用解一种格式
- 区分 4 类:
    1) HTTPException        路由主动抛出的、带语义的错误,原样返回 status + detail
    2) RequestValidationError   pydantic 校验失败,返回 422 + 字段级 detail
    3) StarletteHTTPException   FastAPI 路由匹配不上的 404 / 405 等
    4) Exception(兜底)      没料到的异常,日志记 traceback,响应只暴露通用提示,
                            生产环境严禁泄漏内部细节
- request_id 从 request.state 里读,跟响应头 X-Request-ID 对得上,
  用户报错时把这个 id 给我们 → 直接 grep 日志找到完整调用链
"""

import logging

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from app.core.config import settings

logger = logging.getLogger(__name__)


def _error_payload(code: int, message: str, request: Request, **extra) -> dict:
    """统一构造响应体。"""
    payload = {
        "code": code,
        "message": message,
        "request_id": getattr(request.state, "request_id", "-"),
    }
    if extra:
        payload.update(extra)
    return payload


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """
    路由主动抛 HTTPException 时走这里。
    走 WARNING 不走 ERROR:这是"业务上预期的错误",不是 bug。
    """
    logger.warning(
        "http_exception: status=%d detail=%s path=%s",
        exc.status_code, exc.detail, request.url.path,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(exc.status_code, str(exc.detail), request),
        headers=getattr(exc, "headers", None),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """
    pydantic 校验失败 → 422。
    把 errors() 也带上,前端能精确告诉用户哪个字段错了。
    jsonable_encoder 处理 errors 里的 ValueError 之类不可直接序列化的对象。
    """
    logger.info("validation_error: path=%s errors=%s", request.url.path, exc.errors())
    return JSONResponse(
        status_code=422,
        content=_error_payload(
            422,
            "请求参数校验失败",
            request,
            errors=jsonable_encoder(exc.errors()),
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    最后兜底。任何上面没接住的异常都会进这里。
    - logger.exception 自动记录完整 traceback
    - dev 环境为了排查方便会把异常类型 + 消息塞到响应里
    - 非 dev 一律返回通用消息,绝不向前端泄漏内部细节
    """
    logger.exception("unhandled_exception: path=%s", request.url.path)

    if settings.ENV == "dev":
        message = f"{type(exc).__name__}: {exc}"
    else:
        message = "服务器内部错误,请稍后重试"

    return JSONResponse(
        status_code=500,
        content=_error_payload(500, message, request),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """在 main.py 创建 app 之后调用一次。"""
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
