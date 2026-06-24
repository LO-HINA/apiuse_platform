"""Channel service boundary."""
from __future__ import annotations

import csv
import logging
from uuid import uuid4

from app.core.config import settings
from app.modules.channels import crud, scheduler
from app.modules.channels.schemas import (
    ChannelBulkImportResponse,
    ChannelConfig,
    ChannelCreateRequest,
    ChannelFailureSnapshot,
    ChannelModelOptionsResponse,
    ChannelPublic,
    ChannelUpdateRequest,
)

logger = logging.getLogger(__name__)


class ChannelPoolError(Exception):
    """User-safe channel pool error."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.safe_message = message


def load_channels() -> None:
    crud.load()


def _mask_api_key(api_key: str) -> str:
    if len(api_key) <= 4:
        return "***"
    prefix = api_key[:3] if len(api_key) > 7 else ""
    return f"{prefix}***{api_key[-4:]}"


def _public(channel: ChannelConfig) -> ChannelPublic:
    return ChannelPublic(
        id=channel.id,
        name=channel.name,
        provider_type=channel.provider_type,
        base_url=channel.base_url,
        api_key_masked=_mask_api_key(channel.api_key),
        organization=channel.organization,
        models=channel.models,
        group=channel.group,
        model_redirect=channel.model_redirect,
        weight=channel.weight,
        enabled=channel.enabled,
        blacklisted_until=channel.blacklisted_until,
        success_count=channel.success_count,
        failure_count=channel.failure_count,
        created_at=channel.created_at,
        updated_at=channel.updated_at,
    )


def _new_channel_id() -> str:
    return f"ch_{uuid4().hex[:12]}"


def model_options() -> ChannelModelOptionsResponse:
    return ChannelModelOptionsResponse(
        models=[
            "gpt-4o-mini",
            "gpt-4o",
            "gpt-4.1-mini",
            "gpt-4.1",
            "o4-mini",
            "deepseek-chat",
            "deepseek-reasoner",
            "Qwen/Qwen2.5-72B-Instruct",
        ],
    )


async def list_public_channels() -> list[ChannelPublic]:
    channels = await crud.list_all()
    return [_public(channel) for channel in sorted(channels, key=lambda item: item.created_at)]


async def create_channel(payload: ChannelCreateRequest) -> ChannelPublic:
    models = list(payload.models)
    if payload.custom_model_name and payload.custom_model_name not in models:
        models.append(payload.custom_model_name)
    base_url = payload.base_url or "https://api.openai.com/v1"
    channel = ChannelConfig(
        id=payload.id or _new_channel_id(),
        name=payload.name,
        provider_type=payload.provider_type,
        base_url=base_url,
        api_key=payload.api_key.get_secret_value(),
        organization=payload.organization,
        models=models,
        group=payload.group,
        model_redirect=payload.model_redirect,
        weight=payload.weight,
        enabled=payload.enabled,
    )
    created = await crud.create(channel)
    logger.info("channel created: channel=%s", created.safe_label())
    return _public(created)


async def update_channel(
    channel_id: str, payload: ChannelUpdateRequest,
) -> ChannelPublic | None:
    """更新 channel 静态字段(写文件)。不存在返回 None。

    api_key 以明文提交(管理后台已鉴权),落盘时明文存于 auth 文件。
    custom_model_name 仅在同时提交 models 时追加生效(与 create 一致)。
    """
    fields: dict = {}
    if payload.name is not None:
        fields["name"] = payload.name
    if payload.provider_type is not None:
        fields["provider_type"] = payload.provider_type
    if payload.base_url is not None:
        fields["base_url"] = payload.base_url
    if payload.api_key is not None:
        fields["api_key"] = payload.api_key.get_secret_value()
    if payload.organization is not None:
        fields["organization"] = payload.organization
    if payload.models is not None:
        models = list(payload.models)
        if payload.custom_model_name and payload.custom_model_name not in models:
            models.append(payload.custom_model_name)
        fields["models"] = models
    if payload.group is not None:
        fields["group"] = payload.group
    if payload.model_redirect is not None:
        fields["model_redirect"] = payload.model_redirect
    if payload.weight is not None:
        fields["weight"] = payload.weight
    if payload.enabled is not None:
        fields["enabled"] = payload.enabled

    if not fields:
        current = await crud.get(channel_id)
        return _public(current) if current else None

    updated = await crud.update_static(channel_id, **fields)
    if updated is None:
        return None
    logger.info("channel updated: channel=%s", updated.safe_label())
    return _public(updated)


async def delete_channel(channel_id: str) -> bool:
    """删 channel(文件 + runtime 行)。不存在返回 False。"""
    deleted = await crud.delete(channel_id)
    if deleted:
        logger.info("channel deleted: id=%s", channel_id)
    return deleted


async def get_channel_for_export(channel_id: str) -> ChannelConfig | None:
    """返回含明文 api_key 的完整 ChannelConfig,仅供 export 下载端点使用。

    注意:调用方必须确保响应只走文件下载(不进入浏览器可枚举的 JSON 列表)。
    """
    return await crud.get(channel_id)


def _parse_models(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.replace(";", "|").split("|") if item.strip()]


async def bulk_import_channels(raw_text: str) -> ChannelBulkImportResponse:
    created: list[ChannelPublic] = []
    errors: list[str] = []
    skipped = 0

    for line_no, line in enumerate(raw_text.splitlines(), start=1):
        text = line.strip()
        if not text or text.startswith("#"):
            skipped += 1
            continue

        try:
            row = next(csv.reader([text]))
        except csv.Error:
            errors.append(f"line {line_no}: parse_error")
            continue
        if len(row) < 3:
            errors.append(f"line {line_no}: expected name,api_key,base_url")
            continue

        name, api_key, base_url = (item.strip() for item in row[:3])
        models = _parse_models(row[3].strip() if len(row) >= 4 else None)
        try:
            public = await create_channel(
                ChannelCreateRequest(
                    name=name,
                    api_key=api_key,
                    base_url=base_url,
                    models=models,
                )
            )
        except Exception:  # noqa: BLE001 - do not echo raw import rows
            logger.info("channel import skipped: line=%d reason=validation_or_duplicate", line_no)
            errors.append(f"line {line_no}: validation_error")
            continue
        created.append(public)

    return ChannelBulkImportResponse(
        imported=len(created),
        skipped=skipped,
        errors=errors,
        channels=created,
    )


async def select_channel(
    *, exclude_ids: set[str] | None = None, model: str | None = None,
) -> ChannelConfig:
    channels = await crud.list_all()

    # 先按模型过滤——如果指定了 model 但没有 channel 支持，直接报模型级错误
    if model:
        model_usable = scheduler.usable_channels(
            channels, exclude_ids=None, model=model,
        )
        if not model_usable:
            raise ChannelPoolError(f"没有 channel 支持模型 '{model}'，请检查通道配置")

    usable = scheduler.usable_channels(channels, exclude_ids=exclude_ids, model=model)
    selected = scheduler.pick_weighted(usable)
    if selected is None:
        if model:
            raise ChannelPoolError(
                f"支持模型 '{model}' 的 channel 当前都不可用"
                "（已禁用或被拉黑），请稍后重试"
            )
        raise ChannelPoolError("没有可用的上游 channel，请检查通道配置或等待黑名单过期")
    logger.info("channel selected: channel=%s", selected.safe_label())
    return selected


async def mark_success(channel: ChannelConfig) -> None:
    await crud.mark_success(channel.id)
    logger.info("channel success: channel=%s", channel.safe_label())


async def mark_failure(
    channel: ChannelConfig,
    *,
    reason: str,
    retryable: bool,
) -> ChannelFailureSnapshot:
    await crud.mark_failure(
        channel.id,
        retryable=retryable,
        blacklist_seconds=settings.CHANNEL_BLACKLIST_SECONDS,
    )
    snapshot = ChannelFailureSnapshot(
        channel_id=channel.id,
        name=channel.name,
        reason=reason,
        retryable=retryable,
    )
    logger.warning(
        "channel failure: channel=%s reason=%s retryable=%s",
        channel.safe_label(), reason, retryable,
    )
    return snapshot
