"""Admin API for channel accounts."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_admin_user
from app.modules.channels import crud, service
from app.modules.channels.schemas import (
    ChannelBulkImportRequest,
    ChannelBulkImportResponse,
    ChannelCreateRequest,
    ChannelModelOptionsResponse,
    ChannelPublic,
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


@router.get("/{channel_id}/key")
async def get_channel_key(
    channel_id: str,
    _admin: Annotated[UserRecord, Depends(get_admin_user)],
) -> dict:
    channel = await crud.get(channel_id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="channel not found")
    return {"key": channel.api_key}


@router.post("/bulk-import", response_model=ChannelBulkImportResponse)
async def bulk_import_channels(
    payload: ChannelBulkImportRequest,
    _admin: Annotated[UserRecord, Depends(get_admin_user)],
) -> ChannelBulkImportResponse:
    return await service.bulk_import_channels(payload.raw_text)
