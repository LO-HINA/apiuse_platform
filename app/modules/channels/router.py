"""Admin API for channel accounts."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_admin_user
from app.modules.channels import service
from app.modules.channels.schemas import (
    ChannelBulkImportRequest,
    ChannelBulkImportResponse,
    ChannelCreateRequest,
    ChannelModelOptionsResponse,
    ChannelPublic,
)
from app.storage import UserRecord

router = APIRouter(prefix="/api/admin/channels", tags=["channels"])


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


@router.post("/bulk-import", response_model=ChannelBulkImportResponse)
async def bulk_import_channels(
    payload: ChannelBulkImportRequest,
    _admin: Annotated[UserRecord, Depends(get_admin_user)],
) -> ChannelBulkImportResponse:
    return await service.bulk_import_channels(payload.raw_text)
