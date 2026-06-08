# M2: Channel Pool, Failover, and Runtime Cleanup

## Goal

Enter M2 by turning the current single-upstream chat relay into a minimal channel-pool relay that can load multiple OpenAI-compatible upstream channels from JSON, choose enabled channels by weight, fail over on transient upstream failures, and apply the documented in-memory session cleanup policy.

This task also fixes the concrete issues found in the pre-M2 assessment:

- stale project documentation that still references pre-M1.5 paths
- router/service layering drift in auth and sessions
- unsafe stream error text being returned directly to the browser
- missing implementation detail around M2 channel JSON storage and scheduler behavior

## In Scope

### Documentation and comments

- Update project documentation so the current `app/modules/<domain>/` layout is described accurately.
- Add concise, useful implementation comments around new M2 behavior, especially where scheduling, failover, blacklist state, and JSON persistence are easy to misunderstand.
- Keep comments educational but tied to decisions the code actually makes.

### Channel storage

- Add `app/modules/channels/` implementation with schemas, CRUD/service layer, and scheduler logic.
- Store channel configuration in `data/channels.json`.
- Keep `data/` ignored by git. Do not commit real channel data or API keys.
- Include a safe example in `.env.example` or docs only if needed; never include real secrets.

### Scheduler and failover

- Select from channels where `enabled=true` and `blacklisted_until` is empty or expired.
- Use weighted random selection based on `weight`.
- On timeout, connection error, or 5xx upstream response, temporarily blacklist the channel for `CHANNEL_BLACKLIST_SECONDS` and retry another eligible channel.
- On 401, 403, or 404, record a failure but do not automatically blacklist because those usually require manual key/base-url/model repair.
- On 429, treat as retryable for this M2 implementation and temporarily blacklist, because it is a pool-capacity signal.
- If every channel fails or no channel is usable, return a safe service error and avoid leaking API keys or raw upstream bodies.

### Provider integration

- Keep fake mode intact.
- When `USE_FAKE_AI=false`, route real OpenAI-compatible calls through the channel scheduler instead of directly using global `AI_BASE_URL` / `AI_API_KEY`.
- Preserve both streaming and non-streaming provider entry points.
- Keep OpenAI-compatible request/response parsing minimal and understandable.

### Session memory control

- Add M2 total-session cleanup fields and behavior:
  - `MAX_ACTIVE_SESSIONS`
  - `SESSION_IDLE_TTL_MINUTES`
- Track session last access time.
- When cleanup runs, remove message bodies for stale or excess sessions while keeping session metadata.
- Preserve existing per-session `SESSION_MAX_MESSAGES` trim behavior.

### Layering cleanup

- Move auth register/login orchestration into `auth.service` so `auth.router` is thinner.
- Add a `sessions.service` boundary so `sessions.router` does not directly coordinate `sessions_crud` and `messages_crud`.
- Keep cross-module calls consistent with the Trellis backend directory guidelines.

### Error handling

- Ensure SSE stream errors return user-safe messages.
- Log operational details server-side without exposing secrets.
- Keep `[DONE]` behavior intact after handled stream errors.

## Out of Scope

- No billing, quota, virtual-key forwarding, token multipliers, or full RBAC.
- No database, ORM, Alembic, Redis, SQLite, or vector store.
- No React/Vue frontend rewrite.
- No Docker or CI.
- No full pytest suite unless a lightweight local check is already available without adding test dependencies.
- No admin UI unless needed for a tiny smoke route; M3 owns admin UI.

## Acceptance Criteria

- The app imports successfully.
- Fake chat mode still works through the existing dispatch path.
- Real chat mode dispatches through configured channels, not the old single global upstream path.
- Channel config can be loaded from `data/channels.json`; missing file starts with an empty pool.
- Weighted scheduler ignores disabled and currently blacklisted channels.
- Retryable upstream failures trigger failover and temporary blacklist.
- Non-retryable 401/403/404 failures are counted but not blacklisted.
- Stream errors sent to the browser are safe and do not expose API keys, Authorization headers, or raw upstream response bodies.
- M2 session cleanup can clear old/excess message bodies while retaining session metadata.
- `CLAUDE.md` no longer describes stale pre-M1.5 files as current implementation.
- Trellis task context files contain real backend spec entries, not only the seed `_example` row.

## Verification Plan

- Run a no-bytecode Python import smoke check for `app.main`.
- Run targeted Python checks for channel scheduler behavior with in-memory objects.
- Run targeted checks for retry/failover classification if practical without adding dependencies.
- Run `git status --short` and summarize changed files.
