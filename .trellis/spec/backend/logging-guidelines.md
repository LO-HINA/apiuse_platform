# Logging Guidelines

> How logging is done in this project.

---

## Overview

The backend uses Python standard-library `logging`. Do not add a third-party logging framework without an explicit task.

`app/core/logging.py` configures the root logger once from `app/main.py` before the FastAPI app is assembled. Every module should use:

```python
logger = logging.getLogger(__name__)
```

Request IDs are injected into every log record through `RequestIdFilter`, which reads the request ID from `contextvars`.

---

## Log Formats

Development uses a human-readable format:

```text
timestamp | level | request_id | logger | message
```

Non-development environments use one JSON object per line with fixed fields:

```json
{
  "timestamp": "2026-05-22 10:30:15",
  "level": "INFO",
  "logger": "app.modules.chat.router",
  "request_id": "a3f2...",
  "message": "stream chat done: session_id=... reply_len=..."
}
```

If `exc_info` is present, `JsonFormatter` adds an `exception` field. Do not stuff tracebacks into the message string manually.

---

## Log Levels

- `DEBUG`: local diagnostics that should be quiet by default, such as logging initialization details.
- `INFO`: expected lifecycle and business events, such as app startup/shutdown, stream start/done/cancelled, user data load count, and provider client setup.
- `WARNING`: expected client or business errors that are not server bugs, such as route-level `HTTPException` responses.
- `ERROR` / `EXCEPTION`: unexpected failures requiring investigation. Use `logger.exception()` inside exception handlers when traceback is needed.

---

## What to Log

Prefer operational facts that help debug a failed request without leaking content:

- App lifecycle: startup, shutdown, shared `httpx.AsyncClient` initialization/close.
- Request correlation via automatic `request_id`.
- Stream lifecycle: session ID, user ID when safe, message length, history count, reply length, disconnect/cancel status.
- Persistence lifecycle: JSON load count, missing JSON file fallback, write failures if they occur.
- Provider/channel lifecycle in future milestones: selected channel ID/name, provider type, latency, retry/failover outcome, blacklist duration.
- M2 channel lifecycle: selected channel safe label, success/failure count updates, safe failure reason (`http_500`, `http_429`, `ConnectError`, etc.), and whether the failure is retryable.

Use structured message arguments instead of f-strings so formatting is deferred:

```python
logger.info("stream chat done: session_id=%s reply_len=%d", session_id, len(reply))
```

---

## What NOT to Log

Never log:

- Upstream API keys, JWT secrets, bearer tokens, passwords, password hashes, or `.env` values.
- Full `channels.json` or `users.json` contents.
- Full upstream request/response bodies if they may contain prompts, secrets, or provider credentials.
- Raw Authorization headers.
- Browser-visible unmasked key material.
- Raw Pydantic validation error strings for channel config when those errors may include `api_key` input values.

When channel logs need to identify a key, log a safe channel ID/name. Do not log the key itself; only add masked suffixes if a future admin workflow explicitly needs them.

---

## Common Mistakes

- Calling `logging.basicConfig()` in feature modules instead of using `setup_logging()`.
- Creating per-request handlers or duplicate handlers.
- Logging full chat message content when length or count is enough.
- Logging expected validation failures with traceback.
- Logging `channels.json` contents, provider request payloads, or upstream error bodies during failover.
- Losing `request_id` by bypassing the configured root logging pipeline.
