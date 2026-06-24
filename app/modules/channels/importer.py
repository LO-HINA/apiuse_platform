"""Channel 文件格式检测与解析。

channel 静态信息存于 ``data/channels/auth/<channel_id>.json``。存在两种格式:

1. **统一 schema**(本项目新格式): 含 ``base_url`` / ``api_key`` 字段。
2. **openai_key / 旧项目格式**: 含 ``url`` / ``key`` 字段(M2.5 之前 channel
   auth 文件的写法,以及上游 key 导出常见字段名)。

``detect_format`` 判断格式,``parse_unified_schema`` / ``parse_openai_key_json``
分别解析为 :class:`ChannelConfig`。``parse`` 是统一入口,按检测结果派发。

旧格式文件可能内联 ``success_count`` / ``failure_count`` / ``blacklisted_until``
等运行时字段——这里照原样读入 ChannelConfig(默认 0 / None),由
:mod:`app.modules.channels.crud` 在首次读取时把内联值 seed 到
``channels_runtime`` 表(若无对应行)。新格式文件不含运行时字段。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from app.modules.channels.schemas import ChannelConfig

logger = logging.getLogger(__name__)


def detect_format(raw: dict) -> str:
    """判断 raw 属于哪种格式。

    返回 ``"unified"``(含 base_url 或 api_key)或 ``"openai_key"``
    (含 url 或 key)。两者都没有时按 unified 处理,交给 ChannelConfig
    校验报错(上层捕获并跳过该文件)。
    """
    if "base_url" in raw or "api_key" in raw:
        return "unified"
    if "url" in raw or "key" in raw:
        return "openai_key"
    return "unified"


def _parse_dt(value: object) -> datetime | None:
    """容错解析 ISO8601 时间字符串(兼容末尾 'Z')。datetime 原样返回。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def _build(
    raw: dict,
    *,
    base_url: str,
    api_key: str,
) -> ChannelConfig:
    """根据 raw + 已解析的 base_url/api_key 构造 ChannelConfig。"""
    now = datetime.now(timezone.utc)
    return ChannelConfig(
        id=raw.get("id") or f"ch_{uuid4().hex[:12]}",
        name=raw.get("name") or raw.get("label") or base_url or "imported",
        provider_type=raw.get("provider_type", "openai_compat"),
        base_url=base_url,
        api_key=api_key,
        organization=raw.get("organization"),
        models=raw.get("models", []),
        group=raw.get("group", "default"),
        model_redirect=raw.get("model_redirect", {}),
        weight=raw.get("weight", 1),
        enabled=raw.get("enabled", True),
        success_count=raw.get("success_count", 0),
        failure_count=raw.get("failure_count", 0),
        blacklisted_until=_parse_dt(raw.get("blacklisted_until")),
        created_at=_parse_dt(raw.get("created_at")) or now,
        updated_at=_parse_dt(raw.get("updated_at")) or now,
    )


def parse_unified_schema(raw: dict) -> ChannelConfig:
    """解析本项目统一 schema(含 base_url / api_key)。"""
    return _build(
        raw,
        base_url=raw.get("base_url", ""),
        api_key=raw.get("api_key", ""),
    )


def parse_openai_key_json(raw: dict) -> ChannelConfig:
    """解析 openai_key / 旧项目格式(含 url / key)。

    兼容常见字段名变体:``url`` / ``baseURL`` / ``base_url``,
    ``key`` / ``api_key`` / ``token``。
    """
    base_url = (
        raw.get("base_url")
        or raw.get("url")
        or raw.get("baseURL")
        or ""
    )
    api_key = (
        raw.get("api_key")
        or raw.get("key")
        or raw.get("token")
        or ""
    )
    return _build(raw, base_url=base_url, api_key=api_key)


def parse(raw: dict) -> ChannelConfig:
    """按检测结果派发到对应解析器。"""
    if detect_format(raw) == "openai_key":
        return parse_openai_key_json(raw)
    return parse_unified_schema(raw)
