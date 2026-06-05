# Backend Development Guidelines

> Project-specific backend conventions for the FastAPI key-pool relay platform.

---

## Overview

This backend is a simplified OpenAI-compatible key-pool relay and testing platform. The codebase intentionally favors a small, understandable FastAPI service over broad platform features. Current priorities are API key pool scheduling, failover behavior, LLM gateway mechanics, and SSE pass-through.

Use these guidelines to preserve the current DDD-lite module layout, one-way dependencies, in-memory plus JSON storage model, unified error responses, and request-scoped logging.

---

## Pre-Development Checklist

Before changing backend code, read the files that match the layer you will touch:

1. Always read [Directory Structure](./directory-structure.md) for module boundaries and dependency direction.
2. Read [Database Guidelines](./database-guidelines.md) before changing persistence, repositories, CRUD modules, or data files.
3. Read [Error Handling](./error-handling.md) before changing routers, services, exception handlers, or SSE error paths.
4. Read [Logging Guidelines](./logging-guidelines.md) before adding logs, changing middleware, or touching provider/channel code that may contain secrets.
5. Read [Quality Guidelines](./quality-guidelines.md) before any non-trivial backend change.

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | FastAPI entrypoint, core utilities, module boundaries, and file layout | Filled |
| [Database Guidelines](./database-guidelines.md) | Current no-database model, in-memory repos, JSON persistence, and migration boundaries | Filled |
| [Error Handling](./error-handling.md) | Unified error payloads, exception propagation, and SSE error behavior | Filled |
| [Quality Guidelines](./quality-guidelines.md) | Required layering, forbidden patterns, testing expectations, and review checklist | Filled |
| [Logging Guidelines](./logging-guidelines.md) | Standard-library logging, request_id injection, log levels, and secret handling | Filled |

---

## Core Project Constraints

- Do not add billing, quota management, token multipliers, or virtual-key forwarding unless a task explicitly changes the product direction.
- Do not introduce SQLite, Redis, DuckDB, SQLAlchemy, Alembic, or any database until the thresholds in the project conventions are reached and the task explicitly asks for it.
- Keep browser traffic behind the backend proxy. The frontend must not call upstream model providers directly.
- Keep changes small and local. Cross-module reorganizations require an explicit task and confirmation.
- Preserve native HTML/JS for the current frontend unless a future milestone explicitly changes that direction.

---

**Language**: All documentation in this directory should be written in **English**.
