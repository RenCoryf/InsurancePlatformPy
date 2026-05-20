# Chat Server (Python) — Design

**Date:** 2026-05-21
**Status:** Design approved by user 2026-05-21; pending implementation plan.

## Goal

Build the Python server that backs the existing Go `chatgw` WebSocket gateway,
so the platform supports live 1-on-1 support chat with file attachments. Each
user has exactly two chats: a **main** chat (where deal-related conversation
happens) and a **bonus** chat (user-initiated, where bonus-related conversation
happens). Both are 1-on-1 with a pooled support team.

The Go gateway is already implemented and the request/response shapes it sends
to Python are locked by an earlier spec
(`InsurancePlatform/docs/superpowers/specs/2026-05-09-chatgw-implementation-design.md`).
This spec describes only the Python side and the one small Go-side change
required to support namespaced JWT subjects.

## Scope

In scope:
- New Postgres tables (`chats`, `messages`, `files`, `support_agents`).
- New `/internal/...` endpoints called by Go chatgw (auth-validate, persist).
- Public REST under `/api/v1/...` for the customer app and the support app
  (chat listing, history with cursor pagination, file upload/download).
- Admin REST under `/api/v1/admin/...` for managing support agents
  (HTTP Basic Auth against env credentials).
- Support-agent authentication (separate login flow, separate token issuance).
- MinIO file storage (bytes always flow through Python).
- One Go-side change: rename `sidequest` → `bonus` in comments and docs in
  `InsurancePlatform/` (no runtime change; `chat_type` is already passed
  through opaquely on the Go side, but inline doc strings still say
  "sidequest" and must be updated to match the canonical naming).

Out of scope (deferred):
- Read receipts, unread counts, typing indicators, presence, edit, delete,
  reactions, system messages.
- Multi-instance Go gateway / Redis pub/sub (v1 runs a single chatgw process
  with the in-memory hub).
- Rate limiting (Python's responsibility per the chatgw spec, but no caps
  enforced in v1).
- File MIME allowlist (v1 accepts any MIME; size cap is enforced).
- Range requests on file download.
- File garbage collection (orphans from uploads that were never sent live
  forever in v1).
- Support refresh tokens (issued JWTs simply expire; agents re-login).

## Architecture

```
                   ┌──────────────────┐
   user/support ──►│  Go chatgw       │◄──┐
   (WebSocket)     │  (MemHub, v1)    │   │   POST  /internal/auth/ws-validate
                   └──────┬───────────┘   │   POST  /internal/chats/{chat_id}/messages
                          │ WS frames     │   (X-Internal-Secret)
                          ▼               │
                   ┌──────────────────────┴────────┐
                   │  Python FastAPI app           │
                   │                               │
                   │  /internal/...   (Go-facing)  │
                   │  /api/v1/...     (frontend)   │
                   │  /api/v1/admin/... (admin)    │
                   │                               │
                   │  ┌─────────┐   ┌─────────┐    │
                   │  │ Postgres│   │  MinIO  │    │
                   │  └─────────┘   └─────────┘    │
                   └───────────────────────────────┘
```

Three router groups, three auth schemes, three backends. Redis is initialized
in the existing `lifespan` but the chat subsystem does not use it in v1.

## Message lifecycle

1. Client opens WS to Go with JWT subprotocol and `?type=main` (and, for
   support, `&chat_id=<uuid>`).
2. Go calls `POST /internal/auth/ws-validate` on Python. Python verifies the
   JWT, parses the namespaced `sub` claim, looks up the row in `users` or
   `support_agents`, lazy-creates the chat row if this is a user connecting
   for the first time, and returns `{user_id, role, chat_id}`.
3. Client sends a `send_message` or `send_file` envelope. Go forwards it as
   `POST /internal/chats/{chat_id}/messages`. Python validates and persists
   the row in one transaction (with idempotency on `client_msg_id`), bumps
   `chats.last_message_at`, and returns the canonical `message.Message`.
4. Go broadcasts that message via its in-process hub to everyone currently
   joined to `chat_id` (the customer + any support agents).
5. Files: client uploads via `POST /api/v1/files/` (multipart, with a
   `chat_id` form field). Python streams bytes to MinIO and returns
   `{file_id, name, mime, size}`. The client then sends a `send_file`
   envelope referencing that `file_id`. The Go gateway never sees bytes.

## Data model

Four new tables. All additive — `users` and `refresh_tokens` are untouched.

### `chats`

| Column            | Type                                              | Notes                                                                 |
|-------------------|---------------------------------------------------|-----------------------------------------------------------------------|
| `id`              | UUID, PK                                          | Returned to Go as `chat_id`                                           |
| `owner_user_id`   | INTEGER, FK→`users.id`, NOT NULL                  | Chats are user-owned even on the support side; matches existing `users.id` type (`int_pk`) |
| `type`            | TEXT, NOT NULL, CHECK in (`'main'`, `'bonus'`)    | Enum                                                                  |
| `created_at`      | TIMESTAMPTZ, default `now()`                      |                                                                       |
| `last_message_at` | TIMESTAMPTZ, NULL                                 | Bumped on every persist; NULL until first message                     |
|                   |                                                   | **UNIQUE (`owner_user_id`, `type`)** — one row per user per type      |
|                   |                                                   | **INDEX (`last_message_at` DESC NULLS LAST)** — support dashboard sort |

Lazy-created by `/internal/auth/ws-validate`:
- User-side: insert if `(user_id, type)` row is missing. UNIQUE constraint
  serializes concurrent first-connects.
- Support-side: the row must already exist; if not, 404. Support cannot
  fabricate `chat_id`s.

### `messages`

| Column                | Type                                                 | Notes                                                                 |
|-----------------------|------------------------------------------------------|-----------------------------------------------------------------------|
| `id`                  | UUID, PK                                             | Returned as `message.id`                                              |
| `chat_id`             | UUID, FK→`chats.id`, NOT NULL                        | Indexed                                                               |
| `sender_subject_type` | TEXT, NOT NULL, CHECK in (`'user'`, `'support'`)     | Matches JWT namespace                                                 |
| `sender_subject_id`   | INTEGER, NOT NULL                                    | Generic FK by type (no DB FK — target table varies); INTEGER matches `users.id` and `support_agents.id` |
| `kind`                | TEXT, NOT NULL, CHECK in (`'message'`, `'file'`)     | Matches the Go wire format; stored verbatim                           |
| `body`                | TEXT, NULL                                           | Required iff `kind='message'`                                         |
| `file_id`             | UUID, FK→`files.id`, NULL                            | Required iff `kind='file'`                                            |
| `client_msg_id`       | TEXT, NULL                                           | Idempotency + error-frame `ref`                                       |
| `created_at`          | TIMESTAMPTZ, default `now()`                         |                                                                       |
|                       | **CHECK** `(kind='message' AND body IS NOT NULL AND file_id IS NULL) OR (kind='file' AND file_id IS NOT NULL AND body IS NULL)` |                                                                       |
|                       | **UNIQUE (`chat_id`, `client_msg_id`)** WHERE `client_msg_id IS NOT NULL` | Idempotent retries                                                    |
|                       | **INDEX (`chat_id`, `created_at` DESC, `id` DESC)** | Cursor pagination                                                     |

### `files`

| Column                  | Type                                              | Notes                                                                |
|-------------------------|---------------------------------------------------|----------------------------------------------------------------------|
| `id`                    | UUID, PK                                          | Returned as `file_id`                                                |
| `chat_id`               | UUID, FK→`chats.id`, NOT NULL                     | Bound at upload — download auth = "are you in this chat"             |
| `uploader_subject_type` | TEXT, NOT NULL, CHECK in (`'user'`, `'support'`)  |                                                                      |
| `uploader_subject_id`   | INTEGER, NOT NULL                                 |                                                                      |
| `original_name`         | VARCHAR(512), NOT NULL                            | Display only — not part of `minio_key`                               |
| `mime_type`             | VARCHAR(255), NOT NULL                            | Client-claimed                                                       |
| `size_bytes`            | BIGINT, NOT NULL                                  |                                                                      |
| `minio_key`             | VARCHAR(512), UNIQUE, NOT NULL                    | Path in bucket, e.g. `chats/<chat_id>/<file_id>`                     |
| `created_at`            | TIMESTAMPTZ, default `now()`                      |                                                                      |

### `support_agents`

| Column          | Type                              | Notes                                                          |
|-----------------|-----------------------------------|----------------------------------------------------------------|
| `id`            | INTEGER, PK (`int_pk` autoincrement) | Used in JWT `sub` as `"support:<id>"`; matches existing project pattern |
| `login`         | VARCHAR(64), UNIQUE, NOT NULL     | Username chosen by admin                                       |
| `password_hash` | VARCHAR(255), NOT NULL            | bcrypt via existing `passlib`                                  |
| `display_name`  | VARCHAR(100), NOT NULL            |                                                                |
| `is_active`     | BOOLEAN, NOT NULL, default `true` | Soft-disable; blocks login and `/internal/auth/ws-validate`    |
| `created_at`    | TIMESTAMPTZ, default `now()`      |                                                                |

## API surface

### Internal endpoints (Go-facing)

Both require `X-Internal-Secret: <env INTERNAL_SECRET>`. JSON in/out. No JWT.

#### `POST /internal/auth/ws-validate`

Request:
```json
{ "token": "<JWT>", "chat_type": "main" | "bonus", "chat_id_hint": "<uuid or empty>" }
```

Behavior:
1. Decode JWT (`jwt_secret_key`, `HS256`). Reject expired/malformed → 401.
2. Parse `sub`: `"user:<id>"` or `"support:<id>"`. Else → 401.
3. Look up row. Reject if missing or `is_active=false` → 401.
4. Validate `chat_type` ∈ {`main`, `bonus`} → 400 (`code=validation`).
5. Resolve `chat_id`:
   - User: ignore `chat_id_hint`. `INSERT … ON CONFLICT (owner_user_id, type) DO NOTHING RETURNING id`; if empty, `SELECT id WHERE owner_user_id=? AND type=?`.
   - Support: `chat_id_hint` required and must be UUID. `SELECT … WHERE id=?`; 401 if missing (Go's `pyclient` only treats 401/403 as `ErrUnauthorized`; any other 4xx becomes a 5xx in the gateway). Verify `type` matches → 400 if mismatch.
6. Return:
```json
{ "user_id": "user:42" | "support:7", "role": "user" | "support", "chat_id": "<uuid>" }
```

#### `POST /internal/chats/{chat_id}/messages`

Request (Go's `pyclient.persistDTO` shape, verified against
`InsurancePlatform/internal/pyclient/client.go`):
```json
{
  "user_id": "user:42" | "support:7",
  "role":    "user" | "support",
  "kind":    "message" | "file",
  "body":    "<text>",
  "file_id": "<uuid>",
  "client_msg_id": "<opaque>"
}
```

Note: the `kind` values are `"message"` / `"file"` — Go's router translates
the WS-Inbound envelope types `"send_message"` / `"send_file"` before calling
Python.

Behavior:
1. Re-parse namespaced `user_id`; verify row exists / active → 401.
2. Verify `{chat_id}` exists. Membership check:
   - User: `chats.owner_user_id == subject_id`.
   - Support: any active agent passes (pooled).
   - Else → 403 (`code=validation`).
3. Validate by kind:
   - `message`: `body` non-empty, length ≤ `MAX_MESSAGE_BYTES` env, else 400 (`code=validation`) or 413 (`code=payload_too_large` for size).
   - `file`: `file_id` is UUID; `files` row exists with `chat_id == {chat_id}` → else 400 (`reason="file not in chat"`).
   - Other `kind` → 400 (`code=unsupported_type`).
4. Idempotent insert: `INSERT … ON CONFLICT (chat_id, client_msg_id) DO NOTHING RETURNING *`; on conflict, `SELECT` existing row. Status 200 in both cases. Bump `chats.last_message_at` only on actual insert. Single transaction.
5. Store `kind` directly (`"message"` or `"file"`) — no translation step.

Response (canonical `message.Message` shape from
`InsurancePlatform/internal/message/message.go`):
```json
{
  "id":            "<uuid>",
  "chat_id":       "<uuid>",
  "user_id":       "user:42" | "support:7",
  "role":          "user" | "support",
  "kind":          "message" | "file",
  "body":          "<text>",
  "file": {
    "file_id": "<uuid>",
    "name":    "<original_name>",
    "mime":    "<mime_type>",
    "size":    <bytes>,
    "url":     "/api/v1/files/<file_id>/"
  },
  "client_msg_id": "<opaque>",
  "created_at":    "<rfc3339>"
}
```

Field rules:
- `body` is set when `kind == "message"`, omitted when `kind == "file"`.
- `file` object is set when `kind == "file"`, omitted when `kind == "message"`.
- `url` inside `file` is the relative path the frontend uses to fetch bytes —
  Python composes it as `/api/v1/files/<file_id>/`. Frontend prepends host as
  needed.

### Public endpoints (frontend-facing)

`Authorization: Bearer <JWT>`. Role enforced per route. Replaces the existing
`not_implemented` stubs in `app/api/routers/chats.py` and `files.py`.

| Method | Path                                       | Auth          | Purpose                                                                 |
|--------|--------------------------------------------|---------------|-------------------------------------------------------------------------|
| GET    | `/api/v1/chats/`                           | user          | Caller's chats `[{id, type, last_message_at}, ...]`. Lazy-creates `main`. `bonus` only appears once opened. |
| POST   | `/api/v1/chats/`                           | user          | Body `{type: "bonus"}` explicit open / idempotent get for `main`.       |
| GET    | `/api/v1/chats/{chat_id}/messages/`        | user OR support | Cursor history. `?before=<msg_id>&limit=<1..100, default 50>`. Returns `{messages, next_cursor}`. Auth: user owns chat OR active support. |
| POST   | `/api/v1/files/`                           | user OR support | Multipart `file=...`, form `chat_id=<uuid>`. Streams to MinIO. Returns `{file_id, name, mime, size}`. Size cap = `MAX_FILE_BYTES` env. |
| GET    | `/api/v1/files/{file_id}/`                 | user OR support | Streams bytes from MinIO. Headers: stored `Content-Type`, `Content-Length`, `Content-Disposition: inline; filename="..."`. |
| GET    | `/api/v1/support/chats/`                   | support only  | Dashboard listing. `?type=`, `?before=<rfc3339>`, `?limit`, `?include_empty=false`. Returns `{chats, next_cursor}` ordered by `last_message_at DESC NULLS LAST`. |

Stubs explicitly **dropped**: `POST /chats/{chat_id}/messages/` (WS-only),
`POST /chats/{chat_id}/read/`, `GET /chats/{chat_id}/files/`,
`POST /files/presign/`.

### Admin endpoints

HTTP Basic Auth against env `ADMIN_LOGIN` / `ADMIN_PASSWORD`. Constant-time
comparison. No DB lookup.

| Method | Path                                          | Purpose                                                                   |
|--------|-----------------------------------------------|---------------------------------------------------------------------------|
| POST   | `/api/v1/admin/support-agents/`               | Body `{login, password, display_name}`. Bcrypt-hashes password. 409 on `login` collision. |
| GET    | `/api/v1/admin/support-agents/`               | `?active_only=true&limit=50&offset=0`. No hashes in response.             |
| PATCH  | `/api/v1/admin/support-agents/{id}/`          | Any subset of `{display_name, password, is_active}`.                       |
| DELETE | `/api/v1/admin/support-agents/{id}/`          | Soft delete (`is_active=false`). Hard delete is future work.               |

### Support login

| Method | Path                       | Purpose                                                                                              |
|--------|----------------------------|------------------------------------------------------------------------------------------------------|
| POST   | `/api/v1/support/login/`   | Body `{login, password}`. Verifies against `support_agents`. Issues JWT `{sub: "support:<id>", role: "support", subject_type: "support", subject_id: <id>, exp}`. Same `jwt_secret_key`/algorithm as user JWTs. No refresh in v1. |

## Auth model

Five distinct schemes; one dependency per scheme:

| Scheme              | Dependency                  | Used by                                                                   |
|---------------------|-----------------------------|---------------------------------------------------------------------------|
| Bearer (user JWT)   | `get_current_user` (existing) | User-only routes                                                          |
| Bearer (support JWT)| `get_current_support` (new) | Support-only routes (`/support/chats/`)                                   |
| Bearer (either)     | `get_current_subject` (new) | Mixed routes (`/chats/{id}/messages/`, `/files/*`). Returns `(kind, id, row)`. |
| HTTP Basic          | `admin_basic_auth` (new)    | Admin routes                                                              |
| `X-Internal-Secret` | `internal_secret_required` (new) | `/internal/*` routes                                                      |

### User JWT — additive claims

User JWT issuance (`AuthService.login` / `.register` / `.refresh`) currently
emits `user_id: <int>` only. Add two claims alongside (do not remove
`user_id`):
- `sub: "user:<id>"`
- `role: "user"`

`get_current_user` keeps reading `user_id` — no change to that dependency.
The Go gateway parses the namespaced `sub` value Python returns from
`/internal/auth/ws-validate`; Go's `auth.Identity.UserID` field is already
typed as `string`, so no Go runtime change is required for this part.

### Go-side companion change (rename `sidequest` → `bonus` in docs/comments)

Three Go source files and one doc reference the secondary chat type as
`"sidequest"` in inline comments / doc strings. None of these are runtime
constants — Go passes `chat_type` through opaquely. But the naming must
match the canonical "bonus" everywhere:

| File                                                     | Where                                       |
|----------------------------------------------------------|---------------------------------------------|
| `InsurancePlatform/internal/auth/identity.go`            | `ChatType` field comment                    |
| `InsurancePlatform/internal/auth/client.go`              | Package doc-comment example body            |
| `InsurancePlatform/internal/server/ws_handler.go`        | Package doc-comment query-param description |
| `InsurancePlatform/docs/frontend-integration.ru.md`      | Two lines documenting the `type` query param |
| `InsurancePlatform/docs/superpowers/plans/2026-05-09-chatgw-implementation.md` | Two historical references (leave untouched — it's an archived plan) |

The first four get renamed in a companion commit to the
`InsurancePlatform/` repo. The historical plan file (#5) is left as-is — it
records what the project looked like on 2026-05-09 and is not a live spec.

## File flow

**Bucket:** single MinIO bucket (env `MINIO_BUCKET`, default `chat-files`),
created at app startup if absent. Key layout: `chats/<chat_id>/<file_id>`
(both UUIDs; original filename never in the key — preserved only in
`files.original_name`).

**Client:** `minio` Python SDK (synchronous). One instance cached on
`app.state.minio` in `lifespan`. Sync calls dispatched via `asyncio.to_thread`
in async endpoints.

**Upload (`POST /api/v1/files/`):**
1. Resolve subject (`get_current_subject`).
2. Read multipart: `file=<UploadFile>`, form `chat_id=<uuid>`.
3. Look up chat. Authorize: user owns it OR support is active. Else 403.
4. Validate `file.size ≤ MAX_FILE_BYTES`. Else 413 (`payload_too_large`).
5. Generate `file_id = uuid4()`. `minio_key = f"chats/{chat_id}/{file_id}"`.
6. `await asyncio.to_thread(minio.put_object, ...)` streaming from `file.file`.
7. Insert `files` row in one transaction. On DB failure, best-effort
   `minio.remove_object` and re-raise (orphan logged if cleanup fails).
8. Return `{file_id, name, mime, size}`.

**Download (`GET /api/v1/files/{file_id}/`):**
1. Resolve subject.
2. `SELECT * FROM files WHERE id = :file_id` → 404 if missing.
3. Authorize against `files.chat_id`.
4. `StreamingResponse` wrapping a chunked iterator over MinIO `get_object`,
   8 KiB chunks, closes underlying response on disconnect.
5. Headers as listed above. `Cache-Control: private, max-age=0`.

No range requests in v1. No file deletion in v1. Orphans tolerated.

## Error handling

### Internal-endpoint error envelope (Python → Go)

4xx bodies always shaped as:
```json
{ "code": "<enum>", "reason": "<human>" }
```

`code` enum (locked by chatgw spec):

| `code`              | When                                              |
|---------------------|---------------------------------------------------|
| `validation`        | Bad input, missing relation, type mismatch        |
| `unsupported_type`  | `kind` not in {`message`, `file`}                 |
| `payload_too_large` | `body` > `MAX_MESSAGE_BYTES`                      |
| `rate_limited`      | Reserved; not emitted in v1                       |
| `internal`          | Server fault (Go also synthesizes from 5xx)       |

Three validation layers:
1. Pydantic shape validation. A `RequestValidationError` exception handler
   converts FastAPI's default 422 into 400 with the envelope above.
2. Business rules raise `ChatError(code, reason, http_status)`; a global
   handler maps it to the envelope.
3. DB constraints. `UNIQUE(chat_id, client_msg_id)` violation is the
   idempotent-retry path (return existing row, not error). Other constraint
   violations are bugs → 500.

### Public-endpoint errors

Standard FastAPI convention (`HTTPException(status_code, detail)`), matching
existing routes. No special envelope.

### Idempotency

`POST /internal/chats/{chat_id}/messages` with a repeated `client_msg_id`
returns the existing row (200) without bumping `last_message_at`. Achieved by
`INSERT … ON CONFLICT (chat_id, client_msg_id) DO NOTHING RETURNING *`
followed by a `SELECT` if the insert was a no-op.

### Logging

Structured JSON logs via Python `logging` + a JSON formatter. Per-request:
`request_id` (FastAPI middleware), `subject`, `chat_id`, `message_id`. No
message bodies, no tokens.

## Config additions

New env vars read via `pydantic-settings` in `app/core/config.py`:

```
INTERNAL_SECRET        # shared with Go gateway
MAX_MESSAGE_BYTES      # mirrors Go env; default 64_000
MAX_FILE_BYTES         # default 25_000_000

MINIO_ENDPOINT         # "minio:9000"
MINIO_ACCESS_KEY
MINIO_SECRET_KEY
MINIO_BUCKET           # default "chat-files"
MINIO_SECURE           # bool, default false in dev, true in prod

ADMIN_LOGIN
ADMIN_PASSWORD
```

`app/main.py` `lifespan` gains MinIO client init (additive line; existing
Redis init untouched). The hard-coded `localhost:6379` Redis URL is a
pre-existing concern not addressed by this spec.

## File / module layout

Inside `app/`:

```
app/
  api/
    routers/
      chats.py            # fill in stubs (additive completion of placeholders)
      files.py            # fill in stubs
      support.py          # NEW — /api/v1/support/chats/ + /api/v1/support/login/
      admin.py            # NEW — /api/v1/admin/support-agents/*
      internal.py         # NEW — /internal/*
    dependencies.py       # add: get_current_support, get_current_subject,
                          # admin_basic_auth, internal_secret_required
    main_router.py        # add new routers
  models/
    tables/
      chat.py             # NEW
      message.py          # NEW
      file.py             # NEW
      support_agent.py    # NEW
    dto/
      chat.py             # NEW — request/response models
      message.py
      file.py
      support_agent.py
      internal.py         # NEW — shapes consumed by Go gateway
  repositories/
    chat_repository.py    # NEW
    message_repository.py # NEW
    file_repository.py    # NEW
    support_agent_repository.py # NEW
  services/
    chat_service.py       # NEW — business rules (membership, idempotency)
    file_service.py       # NEW — MinIO orchestration
    support_auth_service.py # NEW
    internal_service.py   # NEW — orchestrates the two /internal endpoints
  core/
    config.py             # additive: new env vars
    minio.py              # NEW — client factory
  main.py                 # additive: MinIO client in lifespan
```

The existing two `User` model files (`app/models/tables/user.py` and
`app/models/users/entities.py`) define `users` slightly differently. Neither
is modified by this spec; new tables FK to `users.id` either way since the
column name and type match. Picking one as canonical is a separate concern.

## Testing strategy

Add dev deps: `pytest`, `pytest-asyncio`, `httpx`, `testcontainers[postgres]`
(or `pytest-postgresql`). Tests under `tests/`.

Layers:

| Layer                          | Coverage                                                                              | DB    | MinIO   |
|--------------------------------|---------------------------------------------------------------------------------------|-------|---------|
| Repository                     | Constraints, idempotency, cursor-pagination index usage                               | real  | n/a     |
| Service                        | Auth/ownership rules, lazy-create races, idempotent persist, error mapping            | real  | mocked  |
| API integration                | All endpoints via `TestClient`; JWT issued through real auth path                     | real  | mocked  |
| Internal-contract              | `/internal/...` request/response shapes pinned against Go's `pyclient` fixtures        | real  | mocked  |

Required cases (the minimum set before declaring complete):

1. `ws_validate_user_creates_main_chat_lazily`
2. `ws_validate_user_main_chat_idempotent` (concurrent requests, no UNIQUE violation surfaced)
3. `ws_validate_support_with_unknown_chat_id_404`
4. `ws_validate_support_chat_type_mismatch_400`
5. `persist_message_idempotent_on_client_msg_id` (same row, same response, no `last_message_at` re-bump)
6. `persist_message_file_not_in_chat_400`
7. `persist_message_oversize_body_413_payload_too_large`
8. `messages_history_cursor_pagination` (last page has `next_cursor=null`)
9. `file_upload_user_not_in_chat_403`
10. `file_download_streams_with_correct_headers`
11. `file_upload_db_fail_cleans_minio_object`
12. `support_login_inactive_agent_401`
13. `admin_create_support_agent_409_on_login_collision`
14. `support_chats_listing_orders_by_last_message_at_desc_nulls_last`
15. `pydantic_validation_error_returns_chatgw_envelope`

## Verification gate

Before declaring complete:

Python:
1. `uv run pytest -q` — all green.
2. Manual smoke: `docker-compose up` (Postgres + MinIO + Redis), run Python
   app, run Go `chatgw`, open the existing frontend test harness. Send a
   text message and a file in both `main` and `bonus`; confirm broadcast to a
   second tab logged in as support.

Go (companion change, in `InsurancePlatform/`):
1. `go build ./...`
2. `go test ./... -race -count=1 -timeout 60s`

## Open questions / future work

- Hard-coded Redis URL in `app/main.py` `lifespan` — pre-existing, not
  changed here. Should move to `pydantic-settings` later.
- The two `User` model definitions in the Python codebase — also pre-existing;
  reconciliation deferred.
- MIME allowlist on file upload — accept-all in v1.
- Range requests on file download — out of v1.
- File / message GC — orphans tolerated in v1.
- Support refresh tokens — re-login in v1.
- Multi-instance Go gateway / Redis hub — chatgw spec's Phase B.

## Files referenced but not changed by this spec

In `InsurancePlatform/`:
- `internal/auth/identity.go`, `internal/auth/client.go`,
  `internal/server/ws_handler.go`, `docs/frontend-integration.ru.md` —
  modified only by the companion comment/doc rename listed above (no runtime
  changes).
- All other files in `InsurancePlatform/internal/*` and `cmd/*` —
  unchanged. The chatgw implementation is treated as final.

In `InsurancePlatformPy/`:
- `app/models/tables/user.py`, `app/models/users/entities.py`,
  `app/models/tables/refresh_token.py`, `app/models/users/refresh_token.py`,
  `app/services/auth_service.py` (except for the two added JWT claims
  described above).
- `app/api/routers/auth.py`, `app/api/routers/me.py`, and every other
  existing router not listed in the "File / module layout" section.
