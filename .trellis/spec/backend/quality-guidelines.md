# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

Quality in this project means small, understandable changes that preserve the learning value and architecture of a simplified key-pool relay platform. Do not optimize for enterprise breadth before the project milestone requires it.

The backend should remain easy to reason about: FastAPI boundary, service orchestration, CRUD/storage access, request-scoped logging, and unified error responses.

---

## Required Patterns

- Keep routers thin. Routers handle HTTP/SSE concerns and delegate business work to services.
- Keep business orchestration in `service.py`.
- Keep shared atomic storage in `app/storage/` and module-specific access wrappers in `crud.py`.
- Use Pydantic schemas from the owning module's `schemas.py` for request, response, and SSE event payloads.
- Register cross-cutting behavior in `app/main.py`: middleware, exception handlers, routers, static files, and lifespan resources.
- Use `logging.getLogger(__name__)` and rely on `setup_logging()` for formatting and request IDs.
- Preserve one-way dependencies and module ownership.
- Prefer minimal changes over broad refactors.

---

## Forbidden Patterns

- Adding billing, quotas, token multipliers, virtual-key forwarding, full RBAC, Prometheus/OpenTelemetry, LangChain/LangGraph, WebSocket, Docker, or pytest before the roadmap milestone explicitly requires it.
- Adding any database or ORM before the documented storage thresholds are reached and the task explicitly asks for the migration.
- Making the frontend call upstream model providers directly.
- Importing another module's private CRUD/model internals across domain boundaries.
- Putting domain business logic into `core/` or generic storage repositories.
- Returning inconsistent error response shapes from individual routes.
- Logging secrets, API keys, password hashes, Authorization headers, or full sensitive request/response bodies.
- Holding storage locks while awaiting long upstream provider calls or SSE token streams.

---

## Testing Requirements

The current roadmap places pytest/CI at a later milestone. Do not introduce a full test stack just to satisfy a small documentation or local behavior change.

For backend code changes now, use the smallest meaningful verification available:

- Run targeted syntax/type/import checks when changing Python code.
- Run the app or affected route manually when the change touches FastAPI wiring or SSE behavior.
- For Trellis spec/documentation changes, run the relevant Trellis task validation command.
- If a task explicitly adds tests or reaches the testing milestone, place tests around the route/service/storage behavior being changed.

---

## Code Review Checklist

Reviewers should check:

- Does the change preserve the product scope as a key-pool relay/testing platform?
- Is the changed logic in the correct layer: router, service, CRUD, storage, or core?
- Are cross-module imports going through the intended public boundary?
- Does the change avoid premature databases, frameworks, and observability stacks?
- Are errors returned through the unified error response shape?
- Are SSE frames valid JSON payloads and is `[DONE]` handled correctly?
- Are logs useful without exposing secrets or full prompt/provider payloads?
- Are in-memory and JSON persistence semantics documented and respected?
- Is the change small enough for the task, without unrelated cleanup?

---

## Examples

- `app/modules/chat/router.py` is a good router example: it handles query parameters, HTTP 404 translation, SSE frames, disconnects, and stream response headers.
- `app/modules/chat/service.py` is a good service example: it resolves sessions, manages message persistence, calls provider dispatch, touches sessions, and trims history.
- `app/core/exceptions.py` is a good cross-cutting example: it centralizes response shape and logging behavior for errors.
- `app/core/logging.py` is a good infrastructure example: it centralizes formatters, request ID injection, and uvicorn logger normalization.

---

## Common Mistakes

- Treating the roadmap as permission to build future milestones early.
- Refactoring multiple modules while implementing a single feature.
- Adding helpers before a pattern repeats enough to justify reuse.
- Changing public function shapes without updating all route/service callers.
- Forgetting that sessions and messages are intentionally restart-cleared in the current phase.
