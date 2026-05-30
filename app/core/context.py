"""
请求级别的 context 变量。

学习要点：
- contextvars.ContextVar 在 asyncio 里能把"某次请求的标识"绑在协程链上,
  跨 await 仍能读到正确的值——这是日志要带 request_id 的关键基础
- 跟 threading.local 不同,asyncio 里多个并发请求互不污染
- middleware 进来时 set(),响应离开时 reset(),logger filter 在中间任意位置 get()
"""

from contextvars import ContextVar

# 默认 "-" 而不是 None:logger filter 拼字符串时不需要再判空,
# 启动期间(还没进入请求)的日志也能正常打。
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
