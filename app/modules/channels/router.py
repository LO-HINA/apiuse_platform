"""Admin API for channel accounts.

channel 静态信息走文件持久化(data/channels/auth/*.json),运行时状态走
channels_runtime 表;本路由只做 HTTP 边界,业务在 service/crud。
所有响应中 api_key 均掩码,明文仅通过 ``/{id}/export`` 下载端点提供。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response

from app.api.deps import get_admin_user
from app.modules.channels import crud, service
from app.modules.channels.schemas import (
    ChannelBulkImportRequest,
    ChannelBulkImportResponse,
    ChannelCreateRequest,
    ChannelModelOptionsResponse,
    ChannelPublic,
    ChannelUpdateRequest,
)
from app.storage import UserRecord

router = APIRouter(prefix="/api/admin/channels", tags=["channels"])

public_router = APIRouter(prefix="/api/channels", tags=["channels-public"])


@public_router.get("/models")
async def list_models() -> list[dict]:
    """Return all available models from all channels (no auth required)."""
    channels = await crud.list_all()
    now = datetime.now(timezone.utc)
    models: list[dict] = []
    for ch in channels:
        available = ch.enabled and (
            ch.blacklisted_until is None or ch.blacklisted_until <= now
        )
        for model in ch.models:
            models.append({
                "model": model,
                "channel_name": ch.name,
                "channel_id": ch.id,
                "available": available,
            })
    return models


@router.get("", response_model=list[ChannelPublic])
async def list_channels(
    _admin: Annotated[UserRecord, Depends(get_admin_user)],
) -> list[ChannelPublic]:
    return await service.list_public_channels()


@router.get("/model-options", response_model=ChannelModelOptionsResponse)
async def model_options(
    _admin: Annotated[UserRecord, Depends(get_admin_user)],
) -> ChannelModelOptionsResponse:
    return service.model_options()


@router.post("", response_model=ChannelPublic, status_code=status.HTTP_201_CREATED)
async def create_channel(
    payload: ChannelCreateRequest,
    _admin: Annotated[UserRecord, Depends(get_admin_user)],
) -> ChannelPublic:
    try:
        return await service.create_channel(payload)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="channel id already exists",
        )


@router.put("/{channel_id}", response_model=ChannelPublic)
async def update_channel(
    channel_id: str,
    payload: ChannelUpdateRequest,
    _admin: Annotated[UserRecord, Depends(get_admin_user)],
) -> ChannelPublic:
    updated = await service.update_channel(channel_id, payload)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="channel not found"
        )
    return updated


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(
    channel_id: str,
    _admin: Annotated[UserRecord, Depends(get_admin_user)],
) -> None:
    deleted = await service.delete_channel(channel_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="channel not found"
        )


@router.get("/{channel_id}/export")
async def export_channel(
    channel_id: str,
    _admin: Annotated[UserRecord, Depends(get_admin_user)],
) -> Response:
    """导出单个 channel 为 JSON 文件下载(含明文 api_key)。

    仅供管理后台鉴权后下载;不进入可枚举的列表响应。
    """
    channel = await service.get_channel_for_export(channel_id)
    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="channel not found"
        )
    payload = channel.model_dump_json(indent=2)
    filename = f"{channel.id}.json"
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/bulk-import", response_model=ChannelBulkImportResponse)
async def bulk_import_channels(
    payload: ChannelBulkImportRequest,
    _admin: Annotated[UserRecord, Depends(get_admin_user)],
) -> ChannelBulkImportResponse:
    return await service.bulk_import_channels(payload.raw_text)
