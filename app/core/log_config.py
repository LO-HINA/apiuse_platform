"""
项目日志配置。

学习要点：
- 用 Python 标准库 logging,不引入第三方
- 各模块通过 logging.getLogger(__name__) 拿到自己的 logger,
  这样输出会带上模块路径(例如 app.api.chat),便于定位
- dev 用人类可读格式(带颜色无关、紧凑)；非 dev(staging / prod)用 JSON 一行,
  ELK / Loki / CloudWatch 能直接收集字段
- RequestIdFilter 把 contextvars 里的 request_id 注入每条日志,
  没有这个 filter,JSON 里就不会有 request_id 字段
- 把 uvicorn 自带的几个 logger 也接进同一格式,否则控制台会出现两种风格
"""

import json
import logging
import sys

from app.core.config import settings
from app.core.context import request_id_var


# 人类可读格式：时间 | 级别 | request_id | 模块路径 | 消息
# 示例：2026-05-22 10:30:15 | INFO     | a3f2... | app.api.chat | stream started
HUMAN_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(request_id).8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class RequestIdFilter(logging.Filter):
    """
    给每条 LogRecord 塞一个 request_id 字段,值从 contextvars 取。

    为什么用 Filter 而不是 Adapter:
        Adapter 需要每个调用方 logger.info(extra={...}),侵入业务代码;
        Filter 是"通道"级别的,所有走这个 logger 的日志自动带上,业务无感。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """
    生产环境用的 JSON 单行格式。

    学习要点：
    - 字段固定:timestamp / level / logger / message / request_id,加上有 exc_info 时的 exception
    - 用 json.dumps + ensure_ascii=False,中文不转义,体积更小,排查时肉眼可读
    - traceback 字段单独放,不要塞进 message,不然 ELK 解析索引会抽风
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, DATE_FORMAT),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> None:
    """
    配置全局日志。
    应在 FastAPI 启动入口调用一次,重复调用会重置 handler。
    """
    level = getattr(logging, settings.LOG_LEVEL, logging.INFO)

    # 选 formatter:dev 走人类格式,其他环境一律 JSON
    if settings.ENV == "dev":
        formatter: logging.Formatter = logging.Formatter(HUMAN_LOG_FORMAT, DATE_FORMAT)
    else:
        formatter = JsonFormatter()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    # 清掉之前可能由 uvicorn / basicConfig 装的 handler,避免双倍输出
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(handler)

    # 把 uvicorn 自己的 logger 也接到同一通道。
    # 它默认会装自己的 handler,清掉后让它通过 propagate=True 走 root,
    # 这样 uvicorn 的 access log 也能带上 request_id 与统一格式。
    for noisy_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        noisy_logger = logging.getLogger(noisy_name)
        noisy_logger.handlers.clear()
        noisy_logger.propagate = True

    logging.getLogger(__name__).debug(
        "logging initialized: env=%s level=%s json=%s",
        settings.ENV, settings.LOG_LEVEL, settings.ENV != "dev",
    )
