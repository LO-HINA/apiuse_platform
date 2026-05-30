"""
全局中间件。

当前提供:
- RequestIDMiddleware: 给每个请求分配 / 透传 X-Request-ID,写入 context 变量
  和响应头,使日志 / 异常 / 跨服务追踪都能串起来。
"""

import logging
import uuid

from app.core.context import request_id_var

logger = logging.getLogger(__name__)


class RequestIDMiddleware:
    """
    每个请求一个 UUID,贯穿日志和响应。

    实现选择——为什么用纯 ASGI 而不是 BaseHTTPMiddleware:
        BaseHTTPMiddleware 看似简单（继承 + 实现 dispatch 就行）,但有两个隐藏代价:
        1) 响应被整体缓冲: 它会把 StreamingResponse 的所有 chunk 收完才下发,
           SSE / 大文件下载会失去流式特性——前端"打字机效果"直接报废
        2) 异常发生时,dispatch 中末尾 set headers 那行走不到,错误响应会缺
           X-Request-ID 头
        纯 ASGI 中间件用 send wrapper 在 http.response.start 消息里注入头,
        既不缓冲,也不漏头,是流式应用的正解。

    工作流喵:
        1. 请求进来 → 优先用客户端传来的 X-Request-ID(网关 / Nginx 常会注入),
           没有就 new 一个 UUID4
        2. 写入 contextvar → logger filter 通过 get() 拿到,自动塞进每条日志
        3. 也写到 scope["state"] → 路由内部 request.state.request_id 可读
        4. send wrapper 把 X-Request-ID 注入到响应头(包括异常路径)
        5. reset() → 防止 contextvar 跨请求污染
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # 非 HTTP(lifespan / websocket)直接放行,不掺和
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 取请求头里的 X-Request-ID,没有就生成。ASGI scope["headers"] 是
        # [(b"name", b"value"), ...] 的 list,大小写不敏感按惯例统一小写比较。
        incoming = None
        for name, value in scope.get("headers") or []:
            if name == b"x-request-id":
                incoming = value.decode("latin-1")
                break
        request_id = incoming or str(uuid.uuid4())

        # 写入 ASGI scope.state(FastAPI 会把它暴露成 request.state)
        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id

        # 写入 contextvar 供 logger filter 读取
        token = request_id_var.set(request_id)

        rid_header = (b"x-request-id", request_id.encode("latin-1"))

        async def send_wrapper(message):
            # 在 http.response.start 阶段把 X-Request-ID 加到 headers
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                # 防御:若已经有 x-request-id 就不重复添加
                if not any(h[0] == b"x-request-id" for h in headers):
                    headers.append(rid_header)
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            request_id_var.reset(token)
