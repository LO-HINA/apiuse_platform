# Directory Structure

> How backend code is organized in this project.

---

## Overview

The backend uses a DDD-lite layout. Each domain module owns its router, service, CRUD wrappers, and schemas. Cross-cutting concerns live in `app/core/`. Shared atomic storage primitives live in `app/storage/`. `app/api/deps.py` is the boundary for cross-domain FastAPI dependencies such as current-user and admin-user resolution.

The goal is not to create a large framework. The goal is to keep the key-pool relay understandable, with clear ownership and one-way dependencies.

---

## Directory Layout

```text
app/
├── main.py
├── api/
│   └── deps.py
├── core/
│   ├── config.py
│   ├── context.py
│   ├── exceptions.py
│   ├── logging.py
│   ├── middleware.py
│   └── security.py
├── modules/
│   ├── auth/
│   │   ├── crud.py
│   │   ├── router.py
│   │   ├── schemas.py
│   │   └── service.py
│   ├── chat/
│   │   ├── router.py
│   │   ├── schemas.py
│   │   └── service.py
│   ├── sessions/
│   │   ├── crud.py
│   │   ├── router.py
│   │   ├── schemas.py
│   │   └── service.py
│   ├── messages/
│   │   ├── crud.py
│   │   └── schemas.py
│   ├── channels/
│   │   ├── crud.py
│   │   ├── scheduler.py
│   │   ├── schemas.py
│   │   └── service.py
│   └── ai_providers/
│       ├── fake.py
│       ├── openai_compat.py
│       └── service.py
├── storage/
│   └── repos.py
└── static/
    └── pages/
        └── chat/
            ├── index.html
            ├── script.js
            └── style.css
```

Some future modules are present only as empty package stubs: `plugins`, `context`, `memory`, and `model_logs`. Add real routers, services, CRUD wrappers, and schemas under `app/modules/<domain>/` only when a milestone actually requires them.

`channels` is an active M2 backend module. It intentionally has no `router.py` yet because M3 owns admin APIs and UI. Channel configuration is loaded from `data/channels.json` through `channels.crud`, selected through `channels.scheduler`, and exposed to providers through `channels.service`.

---

## Layer Responsibilities

- `app/main.py`: create the FastAPI app, run lifespan setup/teardown, configure middleware, register exception handlers, mount static files, and include routers.
- `app/core/`: configuration, request context, request ID middleware, security, logging setup, and global exception handling.
- `app/api/deps.py`: FastAPI dependency functions that are shared across domains.
- `app/modules/<domain>/router.py`: HTTP or SSE boundary only. Validate request parameters through FastAPI/Pydantic, translate known service errors to HTTP status codes, and delegate business work.
- `app/modules/<domain>/service.py`: business orchestration for a domain use case. Services may call other modules only through their public service functions unless the project already uses a narrower CRUD wrapper for that domain.
- `app/modules/<domain>/crud.py`: module-local data access wrapper over `app/storage` primitives.
- `app/modules/<domain>/schemas.py`: Pydantic request/response/event schemas owned by the module.
- `app/modules/channels/scheduler.py`: M2 channel selection only. Keep filtering and weighted random selection here; keep HTTP/provider failure handling in provider/service code.
- `app/storage/`: shared atomic repository primitives that are not owned by a single domain.
- `app/static/`: native HTML/JS/CSS test UI. Do not introduce React/Vue for current milestones.

---

## Dependency Direction

Allowed directions:

```text
modules/*             -> storage / core
modules/chat          -> modules/sessions, modules/messages, modules/ai_providers, modules/context
modules/ai_providers  -> modules/channels when scheduling channels
api/deps              -> modules/auth
```

Rules:

- Cross-module calls should go through `service.py` functions.
- Do not import another module's `crud.py`, `models.py`, or private helpers from a router or unrelated service unless the existing module has no service boundary yet and the dependency is explicitly local and narrow.
- `ai_providers` may call `channels.service` to select and update channel runtime state. Do not make `channels` call `ai_providers`; provider-specific request parsing belongs in `ai_providers`.
- Do not make `storage/` depend on `modules/`.
- Do not make `core/` depend on `modules/`, except for narrowly justified app assembly in `main.py`.
- Keep `router.py` thin. In `app/modules/chat/router.py`, the route builds SSE frames and delegates stream preparation/persistence to `chat.service`.

---

## Naming Conventions

- Domain directories use plural nouns when the domain is a collection resource: `sessions`, `messages`, `ai_providers`.
- FastAPI route modules are named `router.py`.
- Business orchestration modules are named `service.py`.
- Data wrapper modules are named `crud.py` inside domain modules.
- Pydantic schemas live in `schemas.py` inside the owning domain.
- Shared repository records use `*Record` dataclasses in `app/storage/repos.py`, for example `SessionRecord`, `MessageRecord`, and `UserRecord`.
- Use `logging.getLogger(__name__)` in every module that logs.

---

## Examples

- `app/main.py` shows app assembly, `setup_logging()`, `RequestIDMiddleware`, `register_exception_handlers(app)`, router registration, and shared `httpx.AsyncClient` lifecycle.
- `app/modules/chat/router.py` shows a thin route/SSE boundary. It catches `LookupError` from the service and translates it to 404.
- `app/modules/chat/service.py` shows business orchestration over sessions, messages, and AI provider dispatch.
- `app/modules/channels/service.py` is the public boundary for M2 channel pool operations.
- `app/modules/channels/scheduler.py` is the scheduler algorithm boundary for enabled/blacklisted filtering and weighted random choice.
- `app/storage/repos.py` shows shared repository primitives and module-level singleton repos.

---

## Common Mistakes

- Putting business orchestration directly in `router.py` instead of `service.py`.
- Importing another domain's `crud.py` from a router or unrelated module.
- Adding a channel router before M3 instead of keeping M2 channel configuration local to `data/channels.json`.
- Adding a database or ORM because it is familiar, even though the current product phase intentionally uses memory plus JSON.
- Placing domain-specific logic in `core/` or `storage/`.
- Creating a new abstraction before there are real repeated call sites.
