# Database Guidelines

> Persistence patterns and conventions for this project.

---

## Overview

The current backend intentionally does not use a database. The active persistence model is memory plus JSON files:

- `SessionRepo` and `MessageRepo` are in-memory only and are cleared on restart.
- `UserRepo` loads `data/users.json` at startup and synchronously flushes changes back to disk.
- `channels.crud` loads `data/channels.json` at startup and flushes channel runtime state back to disk.
- Future plugin configuration is expected to use JSON files before any database migration.

Do not introduce SQLAlchemy, Alembic, SQLite, Redis, DuckDB, or another database unless the task explicitly asks for a milestone that crosses the documented threshold.

---

## Current Storage Patterns

`app/storage/repos.py` is the source of truth for shared storage primitives.

Current records:

- `SessionRecord`: in-memory session metadata, including `last_accessed_at` for M2 LRU/TTL cleanup.
- `MessageRecord`: in-memory messages grouped by `session_id`.
- `UserRecord`: JSON-backed users with `username`, `password_hash`, role, status, and timestamps.
- `ChannelConfig`: JSON-backed channel configuration under `app/modules/channels/schemas.py`. This is domain-owned, not a shared storage record.

Current singleton repos:

```python
session_repo = SessionRepo()
message_repo = MessageRepo()
user_repo = UserRepo(_DATA_DIR / "users.json")
```

Use module-level singleton repos through the existing import path, for example `from app.storage import user_repo`. Do not instantiate extra repos in routers or services.

Channels are different: use `app.modules.channels.crud` and `app.modules.channels.service`. Do not add channel API keys to `app/storage/repos.py`, and do not expose `api_key` through any response schema.

---

## Write Safety

- Repository writes use `asyncio.Lock` to protect in-memory mutation.
- `UserRepo._flush()` writes to a temporary file and then replaces the target file to avoid half-written JSON.
- `UserRepo.load()` is called once in `app/main.py` during FastAPI lifespan startup.
- `channels.crud.load()` is called once in `app/main.py` during FastAPI lifespan startup. Missing `data/channels.json` starts with an empty pool and must not block fake mode.
- `channels.crud` persists `success_count`, `failure_count`, and `blacklisted_until` changes with an atomic temp-file replace.
- Reads are intentionally lightweight and may not take the write lock.
- SSE streams should not hold storage locks while waiting on upstream tokens.

---

## Query Patterns

- Keep data access behind module-local `crud.py` wrappers where that module already has them.
- Services should call CRUD/service functions instead of reaching into raw repo internals.
- Prefer small repository methods with explicit parameters over generic query builders.
- Keep in-memory query behavior obvious: filter lists/dicts, sort where needed, then slice by `limit`.
- Use `settings.SESSION_MAX_MESSAGES` and `messages_crud.trim_history()` to control message window size.
- Use `settings.MAX_ACTIVE_SESSIONS` and `settings.SESSION_IDLE_TTL_MINUTES` through `sessions.service.cleanup_inactive_message_bodies()` for total session cleanup. Cleanup clears message bodies but keeps session metadata.
- Use `settings.CHANNEL_BLACKLIST_SECONDS` through `channels.service.mark_failure()` for retryable channel failures.

Example from `app/modules/chat/service.py`:

```python
rows = await messages_crud.list_recent(session_id, limit=settings.SESSION_MAX_MESSAGES)
```

---

## Transactions

There is no transaction concept in the current in-memory version. Writes are intended to be idempotent and immediately effective.

When a use case needs multiple writes, keep the sequence clear in the service layer. For example, `handle_chat()` resolves the session, stores the user message, dispatches the AI call, stores the assistant reply, touches the session, and trims history.

Do not simulate database-style transactions with broad locks around long operations. In particular, do not hold locks while awaiting upstream provider streams.

Provider failover must not hold channel CRUD locks while awaiting upstream responses. Select the channel, release locks, call the upstream provider, then record success/failure in a short follow-up write.

---

## Migrations

There are no migrations in the current phase.

Only consider moving a module to a database when one of these project thresholds is reached:

- `model_logs` single JSON file grows beyond roughly 50 MB and queries become slow.
- `memory` needs user-scoped similarity search that JSON cannot support.
- `channels` grows beyond roughly 50 records and multiple admins create real write contention.

If a migration is eventually needed, migrate only the affected module. Do not convert the whole app to a database stack as a side effect.

---

## Naming Conventions

- JSON files live under `data/` and must not be committed when they contain secrets or password hashes.
- `data/channels.json` may be a direct JSON array or an object with a `channels` array. Both forms are local-only.
- Repo record classes use `*Record` dataclasses.
- JSON-backed records should serialize timestamps with ISO format, matching `UserRepo._flush()`.
- Public CRUD functions should preserve stable signatures so the storage implementation can change later without rewriting routers.

---

## Common Mistakes

- Adding an ORM, migration framework, or database for convenience before the project needs it.
- Writing directly to `data/users.json` outside `UserRepo`.
- Returning `api_key` from channel code or logging raw `channels.json` validation errors that could include key material.
- Logging or returning values from `password_hash`, API keys, or future `channels.json` secrets.
- Creating repository instances per request.
- Treating in-memory session/message data as durable data.
