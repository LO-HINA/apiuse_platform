from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.core import crypto as key_crypto
from app.modules.api_keys import crud
from app.modules.api_keys.schemas import (
    ApiKeyConfig,
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyPublic,
    ApiKeyRevealResponse,
    ApiKeyUpdateRequest,
)

logger = logging.getLogger(__name__)


def load_keys() -> None:
    crud.load()


def _generate_raw_key() -> str:
    return f"sk-{secrets.token_urlsafe(32)}"


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _mask_key(raw_key: str) -> str:
    if len(raw_key) <= 8:
        return "***"
    return f"{raw_key[:5]}***{raw_key[-4:]}"


def _new_key_id() -> str:
    return f"key_{uuid4().hex[:12]}"


def _public(key_config: ApiKeyConfig) -> ApiKeyPublic:
    return ApiKeyPublic(
        id=key_config.id,
        key_masked=key_config.key_masked,
        name=key_config.name,
        models=key_config.models,
        quota=key_config.quota,
        used_quota=key_config.used_quota,
        status=key_config.status,
        user_id=key_config.user_id,
        expires_at=key_config.expires_at,
        created_at=key_config.created_at,
        updated_at=key_config.updated_at,
    )


async def list_keys_by_user(user_id: str) -> list[ApiKeyPublic]:
    keys = await crud.list_by_user(user_id)
    return [_public(k) for k in sorted(keys, key=lambda x: x.created_at)]


async def list_all_keys() -> list[ApiKeyPublic]:
    keys = await crud.list_all()
    return [_public(k) for k in sorted(keys, key=lambda x: x.created_at)]


def _compute_expires_at(validity_days: int | None) -> datetime | None:
    if validity_days is None or validity_days <= 0:
        return None
    return datetime.now(timezone.utc) + timedelta(days=validity_days)


async def create_key(user_id: str, payload: ApiKeyCreateRequest) -> ApiKeyCreateResponse:
    raw_key = _generate_raw_key()
    key_hash = _hash_key(raw_key)
    key_masked = _mask_key(raw_key)
    models = [m.strip() for m in payload.models if m.strip()]

    key_config = ApiKeyConfig(
        id=_new_key_id(),
        key_hash=key_hash,
        key_masked=key_masked,
        key_encrypted=key_crypto.encrypt(raw_key),
        name=payload.name,
        models=models,
        quota=payload.quota,
        used_quota=0,
        status=payload.status,
        user_id=user_id,
        expires_at=_compute_expires_at(payload.validity_days),
    )

    created = await crud.create(key_config)
    logger.info("api_key created: id=%s user=%s", created.id, user_id)
    return ApiKeyCreateResponse(key=raw_key, key_info=_public(created))


async def update_key(key_id: str, user_id: str, payload: ApiKeyUpdateRequest) -> ApiKeyPublic | None:
    key_config = await crud.get(key_id)
    if key_config is None or key_config.user_id != user_id:
        return None

    fields: dict = {}
    if payload.name is not None:
        fields["name"] = payload.name
    if payload.models is not None:
        fields["models"] = [m.strip() for m in payload.models if m.strip()]
    if payload.quota is not None:
        fields["quota"] = payload.quota
    if payload.validity_days is not None:
        fields["expires_at"] = _compute_expires_at(payload.validity_days)
    if payload.status is not None:
        fields["status"] = payload.status

    if not fields:
        return _public(key_config)

    updated = await crud.update(key_id, **fields)
    if updated is None:
        return None
    logger.info("api_key updated: id=%s user=%s fields=%s", key_id, user_id, list(fields.keys()))
    return _public(updated)


async def revoke_key(key_id: str, user_id: str) -> ApiKeyPublic | None:
    key_config = await crud.get(key_id)
    if key_config is None or key_config.user_id != user_id:
        return None
    updated = await crud.update_status(key_id, "disabled")
    if updated is None:
        return None
    logger.info("api_key revoked: id=%s user=%s", key_id, user_id)
    return _public(updated)


async def verify_key(raw_key: str) -> ApiKeyConfig | None:
    key_hash = _hash_key(raw_key)
    return await crud.get_by_key_hash(key_hash)


async def delete_key(key_id: str) -> bool:
    result = await crud.delete(key_id)
    if result:
        logger.info("api_key deleted: id=%s", key_id)
    return result


async def reveal_key(key_id: str, user_id: str) -> ApiKeyRevealResponse | None:
    key_config = await crud.get(key_id)
    if key_config is None or key_config.user_id != user_id:
        return None
    if not key_config.key_encrypted:
        return None
    try:
        raw_key = key_crypto.decrypt(key_config.key_encrypted)
    except Exception:
        logger.error("api_key decrypt failed: id=%s", key_id)
        return None
    logger.info("api_key revealed: id=%s user=%s", key_id, user_id)
    return ApiKeyRevealResponse(key=raw_key)
