"""Channel 持久化:文件 IO(静态信息) + channels_runtime 表(运行时状态)。

- 静态信息(name/base_url/api_key/models/weight/enabled/...)存于
  ``data/channels/auth/<channel_id>.json``,明文 api_key,atomic temp-file replace。
- 运行时状态(success_count / failure_count / blacklisted_until)存于
  SQLite ``channels_runtime`` 表,重启后保留。
- 旧格式文件(``url``/``key``)通过 :mod:`app.modules.channels.importer` 透明解析。
- 旧文件内联的运行时字段,在首次读取且 runtime 行缺失时 seed 到表(保留历史计数)。
- 文件写用模块级 ``asyncio.Lock``;不在持锁期间发起上游调用。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.database import get_db
from app.modules.channels import importer
from app.modules.channels.schemas import ChannelConfig

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
AUTH_DIR = _DATA_DIR / "channels" / "auth"

_file_lock = asyncio.Lock()

# 允许 update_static 修改的静态字段白名单
_STATIC_FIELDS = frozenset(
    {
        "name",
        "provider_type",
        "base_url",
        "api_key",
        "organization",
        "models",
        "group",
        "model_redirect",
        "weight",
        "enabled",
    }
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load() -> None:
    """占位:channel 现按需从文件扫描(list_all / get),无需启动期显式 load。"""
    logger.debug("channels load skipped — file-based persistence, scanned on demand")


# ---------------------------------------------------------------------------
# 文件读写原语
# ---------------------------------------------------------------------------

def _atomic_write_json(path: Path, data: dict) -> None:
    """原子写:先写 .tmp 再 os.replace,防止半写文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(tmp, path)


def _config_to_dict(cfg: ChannelConfig) -> dict:
    """ChannelConfig → 文件 dict(仅静态字段,明文 api_key,不含 runtime)。"""
    return {
        "id": cfg.id,
        "name": cfg.name,
        "provider_type": cfg.provider_type,
        "base_url": cfg.base_url,
        "api_key": cfg.api_key,
        "organization": cfg.organization,
        "models": list(cfg.models),
        "group": cfg.group,
        "model_redirect": dict(cfg.model_redirect),
        "weight": cfg.weight,
        "enabled": cfg.enabled,
        "created_at": cfg.created_at.isoformat(),
        "updated_at": cfg.updated_at.isoformat(),
    }


def _read_file(channel_id: str) -> ChannelConfig | None:
    """同步读单个 channel 文件并解析。文件缺失/损坏返回 None。"""
    f = AUTH_DIR / f"{channel_id}.json"
    if not f.exists():
        return None
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("channels: skip malformed file %s: %s", f.name, exc)
        return None
    try:
        return importer.parse(raw)
    except Exception as exc:  # noqa: BLE001 — 解析失败不能拖垮 list_all
        logger.warning("channels: skip unparseable file %s: %s", f.name, exc)
        return None


# ---------------------------------------------------------------------------
# runtime 表原语
# ---------------------------------------------------------------------------

async def _read_runtime(db, channel_id: str) -> tuple[bool, int, int, datetime | None]:
    """返回 (row_exists, success_count, failure_count, blacklisted_until)。"""
    cursor = await db.execute(
        "SELECT success_count, failure_count, blacklisted_until "
        "FROM channels_runtime WHERE channel_id = ?",
        (channel_id,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        return False, 0, 0, None
    bl = row["blacklisted_until"]
    bl_dt = datetime.fromisoformat(bl) if bl else None
    return True, row["success_count"], row["failure_count"], bl_dt


async def _ensure_runtime_row(
    db,
    channel_id: str,
    *,
    success: int = 0,
    failure: int = 0,
    blacklisted_until: str | None = None,
) -> None:
    """INSERT OR IGNORE 一行 runtime;已有行不覆盖。可携带 seed 值(旧文件内联)。"""
    await db.execute(
        "INSERT OR IGNORE INTO channels_runtime "
        "(channel_id, success_count, failure_count, blacklisted_until) "
        "VALUES (?, ?, ?, ?)",
        (channel_id, success, failure, blacklisted_until),
    )
    await db.commit()


async def _attach_runtime(cfg: ChannelConfig) -> ChannelConfig:
    """把 runtime 表的计数贴到 cfg 上;行缺失时按需 seed(旧文件内联值或默认 0)。"""
    db = get_db()
    exists, success, failure, bl = await _read_runtime(db, cfg.id)
    if not exists:
        # 优先用旧文件内联的 runtime 值 seed;新格式文件这些字段为 0/None
        seed_success = cfg.success_count
        seed_failure = cfg.failure_count
        seed_bl_iso = cfg.blacklisted_until.isoformat() if cfg.blacklisted_until else None
        await _ensure_runtime_row(
            db,
            cfg.id,
            success=seed_success,
            failure=seed_failure,
            blacklisted_until=seed_bl_iso,
        )
        success, failure, bl = seed_success, seed_failure, cfg.blacklisted_until
    cfg.success_count = success
    cfg.failure_count = failure
    cfg.blacklisted_until = bl
    return cfg


# ---------------------------------------------------------------------------
# 公开 CRUD
# ---------------------------------------------------------------------------

async def count() -> int:
    """统计 auth 目录下 json 文件数。"""
    if not AUTH_DIR.exists():
        return 0
    return sum(1 for _ in AUTH_DIR.glob("*.json"))


async def list_all() -> list[ChannelConfig]:
    """扫描 auth/*.json + join channels_runtime,按 created_at 升序返回。"""
    if not AUTH_DIR.exists():
        return []
    configs: list[ChannelConfig] = []
    for f in sorted(AUTH_DIR.glob("*.json")):
        cfg = _read_file(f.stem)
        if cfg is None:
            continue
        await _attach_runtime(cfg)
        configs.append(cfg)
    configs.sort(key=lambda c: c.created_at)
    return configs


async def get(channel_id: str) -> ChannelConfig | None:
    """读单个 channel(文件 + runtime)。文件不存在返回 None。"""
    cfg = _read_file(channel_id)
    if cfg is None:
        return None
    return await _attach_runtime(cfg)


async def create(channel: ChannelConfig) -> ChannelConfig:
    """生成文件 + 默认 runtime 行。id 冲突抛 ValueError。"""
    async with _file_lock:
        f = AUTH_DIR / f"{channel.id}.json"
        if f.exists():
            raise ValueError("channel id already exists")

        # 时间规范化
        if channel.created_at.tzinfo is None:
            channel.created_at = channel.created_at.replace(tzinfo=timezone.utc)
        channel.updated_at = _now()

        _atomic_write_json(f, _config_to_dict(channel))

        # 默认 runtime 行(新创建计数归零)
        db = get_db()
        await _ensure_runtime_row(db, channel.id)
        channel.success_count = 0
        channel.failure_count = 0
        channel.blacklisted_until = None

    logger.info("channel file created: id=%s name=%s", channel.id, channel.name)
    return channel


async def update_static(channel_id: str, **fields) -> ChannelConfig | None:
    """更新 auth/<id>.json 的静态字段。文件不存在返回 None。

    只接受 _STATIC_FIELDS 内的字段且值非 None;更新后 re-validate 并刷新 updated_at。
    """
    async with _file_lock:
        f = AUTH_DIR / f"{channel_id}.json"
        if not f.exists():
            return None
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("channels update_static: malformed file %s: %s", channel_id, exc)
            return None
        try:
            cfg = importer.parse(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("channels update_static: unparseable file %s: %s", channel_id, exc)
            return None

        changed = False
        for key, value in fields.items():
            if key in _STATIC_FIELDS and value is not None:
                setattr(cfg, key, value)
                changed = True
        if not changed:
            # 无可更新字段,直接返回当前(带 runtime)
            return await get(channel_id)

        cfg.updated_at = _now()
        # re-validate(例如 base_url 非空、weight 范围)
        cfg = ChannelConfig(**cfg.model_dump())
        _atomic_write_json(f, _config_to_dict(cfg))

    logger.info("channel file updated: id=%s fields=%s", channel_id, list(fields.keys()))
    return await get(channel_id)


async def update_runtime(channel_id: str, **fields) -> None:
    """通用 runtime 字段绝对值更新(success_count / failure_count / blacklisted_until)。

    行不存在时先 INSERT 默认行。用于管理后台重置计数等场景;
    自增场景请用 :func:`mark_success` / :func:`mark_failure`(原子)。
    """
    db = get_db()
    await _ensure_runtime_row(db, channel_id)

    sets: list[str] = []
    vals: list[object] = []
    if "success_count" in fields and fields["success_count"] is not None:
        sets.append("success_count = ?")
        vals.append(int(fields["success_count"]))
    if "failure_count" in fields and fields["failure_count"] is not None:
        sets.append("failure_count = ?")
        vals.append(int(fields["failure_count"]))
    if "blacklisted_until" in fields:
        bl = fields["blacklisted_until"]
        sets.append("blacklisted_until = ?")
        vals.append(bl.isoformat() if isinstance(bl, datetime) else bl)
    if not sets:
        return

    vals.append(channel_id)
    await db.execute(
        f"UPDATE channels_runtime SET {', '.join(sets)} WHERE channel_id = ?",
        vals,
    )
    await db.commit()


async def mark_success(channel_id: str) -> None:
    """原子自增 success_count 并清空黑名单。"""
    db = get_db()
    await _ensure_runtime_row(db, channel_id)
    await db.execute(
        "UPDATE channels_runtime SET success_count = success_count + 1, "
        "blacklisted_until = NULL WHERE channel_id = ?",
        (channel_id,),
    )
    await db.commit()


async def mark_failure(
    channel_id: str,
    *,
    retryable: bool,
    blacklist_seconds: int,
) -> None:
    """原子自增 failure_count;retryable 时设置黑名单到期时间。"""
    blacklisted_until = (
        (_now() + timedelta(seconds=blacklist_seconds)).isoformat()
        if retryable and blacklist_seconds > 0
        else None
    )
    db = get_db()
    await _ensure_runtime_row(db, channel_id)
    if blacklisted_until is not None:
        await db.execute(
            "UPDATE channels_runtime SET failure_count = failure_count + 1, "
            "blacklisted_until = ? WHERE channel_id = ?",
            (blacklisted_until, channel_id),
        )
    else:
        await db.execute(
            "UPDATE channels_runtime SET failure_count = failure_count + 1 "
            "WHERE channel_id = ?",
            (channel_id,),
        )
    await db.commit()


async def delete(channel_id: str) -> bool:
    """删 auth/<id>.json + 对应 runtime 行。文件不存在返回 False。"""
    async with _file_lock:
        f = AUTH_DIR / f"{channel_id}.json"
        if not f.exists():
            return False
        try:
            f.unlink()
        except OSError as exc:
            logger.warning("channels delete: unlink failed id=%s: %s", channel_id, exc)
            return False
        db = get_db()
        await db.execute(
            "DELETE FROM channels_runtime WHERE channel_id = ?", (channel_id,)
        )
        await db.commit()
    logger.info("channel file deleted: id=%s", channel_id)
    return True
