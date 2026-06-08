# Error Handling

> How errors are handled in this project.

---

## Overview

HTTP errors are normalized by global handlers in `app/core/exceptions.py`. Clients should receive one response shape for normal API failures:

```json
{
  "code": 404,
  "message": "session not found",
  "request_id": "..."
}
```

The `request_id` comes from request state and should match the `X-Request-ID` response header so users can report an ID that maps back to logs.

---

## Error Types

Current handlers cover four categories:

- `StarletteHTTPException` / FastAPI `HTTPException`: expected route-level semantic errors. These are logged at warning level and returned with their status code and detail.
- `RequestValidationError`: Pydantic/FastAPI validation failures. These return 422 and include encoded `errors` details.
- `Exception`: unexpected fallback errors. These log a traceback and return 500.
- SSE stream exceptions: handled inside the event generator so the frontend can receive an error event before stream termination.

The project does not currently define a large custom exception hierarchy. Use built-in exceptions only when they are translated at the right boundary. For example, `chat.service` raises `LookupError("session not found")`, and `chat.router` translates it into a 404 `HTTPException`.

---

## Error Handling Patterns

- Services may raise narrow, expected Python exceptions when the router owns the HTTP translation.
- Routers translate expected service failures to `HTTPException` with a clear status code.
- Let unexpected exceptions reach the global exception handler for normal JSON APIs.
- For SSE routes, catch broad exceptions inside the generator, log with `logger.exception()`, emit an error event, and then finish the stream protocol.
- Re-raise `asyncio.CancelledError` in SSE generators. Client disconnects and shutdown cancellation must not be swallowed.

Example from `app/modules/chat/router.py`:

```python
try:
    current_session_id, history = await chat_service.prepare_stream(...)
except LookupError:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="session not found",
    )
```

---

## API Error Responses

Use `_error_payload()` from `app/core/exceptions.py` through registered handlers. Do not hand-build a different response format in individual routers.

Standard fields:

- `code`: HTTP status code.
- `message`: user-safe error message.
- `request_id`: request correlation ID.

Validation errors may additionally include:

- `errors`: encoded validation details from Pydantic/FastAPI.

In `dev`, unhandled 500 responses include exception type and message to support learning/debugging. Outside `dev`, unhandled 500 responses must not leak internal details.

---

## SSE Error Responses

SSE routes have protocol-specific behavior:

- The first event should expose `session_id` because `EventSource` cannot read custom response headers.
- Tokens must be encoded as JSON event payloads so embedded newlines do not break the SSE frame format.
- Stream errors should be sent as a JSON error event with a user-safe message. Prefer `safe_message` from a known service exception such as `ChannelPoolError`; otherwise use a generic message. Do not send `str(exc)` directly to the browser.
- `[DONE]` should be emitted when the stream exits normally or after a handled stream error, unless the client disconnected.

Keep SSE protocol framing in the router/stream boundary. Business decisions such as preparing history or persisting assistant messages belong in `chat.service`.

M2 channel/provider failures:

- 5xx, 429, timeouts, connection errors, and invalid upstream JSON are retryable channel failures.
- 401, 403, and 404 are counted as failures but are not blacklisted automatically.
- When the channel pool is exhausted, return a safe error message. Never expose upstream URLs with embedded credentials, raw upstream response bodies, Authorization headers, or API keys.
- Streaming failover may retry only before any token has been emitted. Once tokens have reached the browser, a mid-stream upstream failure should become a safe stream error instead of switching channels and duplicating output.

---

## Common Mistakes

- Returning ad hoc error dictionaries from routers instead of raising `HTTPException` or using global handlers.
- Leaking upstream provider errors, API keys, raw response bodies, or internal stack details to clients.
- Using `str(exc)` for SSE/provider errors that may contain upstream details.
- Swallowing `asyncio.CancelledError` in a stream generator.
- Logging expected 404/validation errors as server errors.
- Putting HTTP status-code decisions deep inside storage repositories.
