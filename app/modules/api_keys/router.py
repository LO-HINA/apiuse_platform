from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_admin_user, get_authenticated_user
from app.modules.api_keys.schemas import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyPublic,
    ApiKeyRevealResponse,
    ApiKeyUpdateRequest,
)
from app.modules.api_keys import crud, service
from app.storage import UserRecord

router = APIRouter(prefix="/api/admin/keys", tags=["api-keys"])

user_router = APIRouter(prefix="/api/keys", tags=["api-keys-user"])


@router.get("", response_model=list[ApiKeyPublic])
async def admin_list_keys(
    _admin: Annotated[UserRecord, Depends(get_admin_user)],
) -> list[ApiKeyPublic]:
    return await service.list_all_keys()


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_key(
    key_id: str,
    _admin: Annotated[UserRecord, Depends(get_admin_user)],
) -> None:
    deleted = await service.delete_key(key_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="key not found")


@user_router.get("", response_model=list[ApiKeyPublic])
async def list_my_keys(
    current_user: Annotated[UserRecord, Depends(get_authenticated_user)],
) -> list[ApiKeyPublic]:
    return await service.list_keys_by_user(current_user.id)


@user_router.post("", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_key(
    payload: ApiKeyCreateRequest,
    current_user: Annotated[UserRecord, Depends(get_authenticated_user)],
) -> ApiKeyCreateResponse:
    try:
        return await service.create_key(current_user.id, payload)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="key id already exists",
        )


@user_router.put("/{key_id}", response_model=ApiKeyPublic)
async def update_my_key(
    key_id: str,
    payload: ApiKeyUpdateRequest,
    current_user: Annotated[UserRecord, Depends(get_authenticated_user)],
) -> ApiKeyPublic:
    result = await service.update_key(key_id, current_user.id, payload)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="key not found")
    return result


@user_router.put("/{key_id}/revoke", response_model=ApiKeyPublic)
async def revoke_key(
    key_id: str,
    current_user: Annotated[UserRecord, Depends(get_authenticated_user)],
) -> ApiKeyPublic:
    result = await service.revoke_key(key_id, current_user.id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="key not found")
    return result


@user_router.post("/{key_id}/reveal", response_model=ApiKeyRevealResponse)
async def reveal_key(
    key_id: str,
    current_user: Annotated[UserRecord, Depends(get_authenticated_user)],
) -> ApiKeyRevealResponse:
    result = await service.reveal_key(key_id, current_user.id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="key not found or decrypt failed")
    return result


@user_router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_key(
    key_id: str,
    current_user: Annotated[UserRecord, Depends(get_authenticated_user)],
) -> None:
    existing = await crud.get(key_id)
    if existing is None or existing.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="key not found")
    deleted = await service.delete_key(key_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="key not found")
