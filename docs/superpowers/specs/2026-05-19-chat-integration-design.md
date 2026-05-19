# Chat Integration Design — Python Server for Go `chatgw`

**Status:** Approved design; ready for implementation planning.
**Date:** 2026-05-19
**Scope:** Implement the Python (FastAPI) server side that the Go `chatgw` WebSocket gateway depends on, plus the public chat and file endpoints needed for a working frontend.

---

## 1. Context

The repo contains two services:

- **`InsurancePlatform/`** — a Go WebSocket relay gateway (`chatgw`). It holds open WS connections from customers and support agents, calls Python to validate the JWT at connect time, calls Python to persist each inbound message, and fans the persisted message out to participants. It carries no business logic and no state beyond live connections.
- **`InsurancePlatformPy/`** — a FastAPI service that owns user accounts, SMS auth, JWT issuance, and (per the existing scaffolding) the rest of the insurance domain. Most domain routers are currently `not_implemented()` placeholders.

Today the integration **does not work end-to-end**: Go calls two Python endpoints (`POST /internal/auth/ws-validate` and `POST /internal/chats/{chat_id}/messages`) that don't exist, and the supporting data model (chats, messages, files, support-role users) hasn't been built.

This spec covers the work needed in `InsurancePlatformPy` to make the chat feature functional, including file attachments.

### Guiding principle: additive over invasive

The Python codebase is an in-progress scaffold. Existing files and patterns are *retained*. New code goes in new files even if a sibling file looks like it could absorb it. Schema changes on existing tables are nullable with defaults so existing flows keep working without changes. Established conventions (router → service → repository → model/tables) are followed for new code rather than introducing alternatives. No refactoring of existing services, no renaming, no sweeping cleanup.

### Chat semantics

- Each user has **two 1-on-1 chats** with support, auto-created at registration:
  - `main` — bonuses chat (general support / account / bonuses).
  - `sidequest` — deals chat (everything deal-related — one chat covers all of a user's deals).
- Both chats are created eagerly in the same DB transaction as the new user row. A one-shot Alembic data migration backfills the two chats for any pre-existing users.
- "Any support agent" can open any chat; there is no per-chat assignment in v1.

### User roles

- `user` — customer. Authenticates via SMS code, then JWT (existing flow).
- `support` — agent. Created by a CLI seeder, set by hand. Authenticates via login + password, then JWT (new flow).
- Admin functionality (creating/listing/disabling support users via HTTP) is **out of scope** for this spec. Support users are seeded via `app/scripts/create_support_user.py`.

---

## 2. Architecture overview

```
                Browser/Client
                     │
        ┌────────────┼────────────────────┐
        │            │                    │
   HTTPS REST    WS upgrade           HTTPS PUT
        │            │                    │
        ▼            ▼                    ▼
  ┌──────────┐  ┌─────────────┐    ┌─────────┐
  │  Python  │  │ Go chatgw   │    │  MinIO  │
  │ FastAPI  │◄─┤             │    │  (S3)   │
  │  :8000   │  │   :8080     │    │  :9000  │
  └─────┬────┘  └──────┬──────┘    └─────────┘
        │              │
        │              │ (HTTP, X-Internal-Secret)
        │              ▼
        │         ┌──────────────────────┐
        └────────►│ /internal/auth/ws-validate
                  │ /internal/chats/{id}/messages
                  └──────────────────────┘
        Postgres (chats, messages, chat_files, users)
```

- Browser uses HTTPS REST for everything except live messaging: register/login, list chats, fetch history, request a presigned upload URL, list files.
- For live messaging the browser opens a WS to Go (`chatgw`). Go validates the JWT and persists each message by calling Python's `/internal/*` endpoints under a shared secret.
- File bytes go **directly from the browser to MinIO** via a presigned PUT URL Python issues. Python only touches MinIO for presign generation and one HEAD per file upload (during the confirm step) — never on the message hot path.

---

## 3. Module layout

### New files

```
app/
  models/tables/
    chat.py                       Chat ORM model
    message.py                    Message ORM model
    chat_file.py                  ChatFile ORM model
  models/dto/
    chat.py                       Pydantic DTOs for chat/message/file responses
    internal.py                   Pydantic DTOs for /internal/* request/response shapes
  services/
    chat_service.py               Chat resolution, message persistence, history
    file_service.py               Presign, confirm, MinIO client wrapper
    support_auth_service.py       Password login for support users
    internal_token_service.py     JWT validation for ws-validate
  repositories/
    chat_repository.py
    message_repository.py
    file_repository.py
  api/routers/
    internal.py                   /internal/auth/ws-validate, /internal/chats/{id}/messages
    files.py                      /api/v1/files/
    support_auth.py               /api/v1/auth/support/login/
  api/dependencies/
    internal_secret.py            X-Internal-Secret check
  core/
    minio.py                      MinIO/S3 client factory
  scripts/
    create_support_user.py        CLI seeder
alembic.ini
alembic/
  env.py
  script.py.mako
  versions/
    0001_baseline.py
    0002_add_role_login_to_users.py
    0003_chat_domain.py
tests/                             see Section 10
```

### Touched existing files (minimal diffs)

| File | Change |
|---|---|
| `app/models/tables/user.py` | Add `role` (default `"user"`) and `login` (nullable, unique) columns. |
| `app/models/base.py` | Add `uuid_pk` annotation alongside existing `int_pk`. |
| `app/services/auth_service.py` | `_generate_access_token` takes an optional `role` parameter (defaults `"user"`). `register()` calls `ChatService.ensure_user_chats(user.id)` inside its existing transaction. Token-generation and refresh-token helpers promoted to module-level functions for reuse by `SupportAuthService`. |
| `app/api/main_router.py` | Add `include_router(files_router)` and `include_router(support_auth_router)`. |
| `app/main.py` | `app.include_router(internal_router)` (mounted outside `/api/v1`). Add a startup hook that ensures the MinIO bucket exists. |
| `app/api/routers/chats.py` | Replace `not_implemented()` bodies for `GET /chats/`, `POST /chats/`, `GET /chats/{id}/messages/`, `GET /chats/{id}/files/`. Leave `POST /chats/{id}/messages/` and `POST /chats/{id}/read/` stubbed. |
| `app/core/config.py` | Add settings for `internal_secret`, MinIO connection, file size/mime limits, message body limit. |
| `pyproject.toml` | Add `alembic`, `aioboto3`, `python-multipart`. Add dev dependencies (pytest, pytest-asyncio, httpx, freezegun). |
| `docker-compose.yml` | Add `minio` and `minio-init` services, plus a `minio_data` volume. |

### Untouched

- Existing SMS auth flow (`request-code`, `register`, `login`, `refresh`, `logout`) — register gets one added call; the rest unchanged.
- All other domain routers (`applications`, `deals`, `bonuses`, `certificates`, `partners`, `referrals`, `reports`, `me`).
- `services/sms_service.py`, `services/referral_service.py`, `services/code_generator.py`.
- `Dockerfile`.

---

## 4. Data model

All new tables follow the existing convention (snake_case plural, `TimestampMixin` for timestamps where appropriate).

### `users` — modified

Two new columns:

```python
role: Mapped[str] = mapped_column(String(20), nullable=False, server_default="user")
login: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
```

- `role` values: `"user"` (default) or `"support"`. No DB CHECK constraint — enforced at the application layer.
- `login` is set only for support users (by the CLI seeder); regular customers leave it `NULL`.

### `chats` — new

```python
class Chat(Base, TimestampMixin):
    __tablename__ = "chats"

    id: Mapped[uuid_pk]
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)   # "main" | "sidequest"

    __table_args__ = (UniqueConstraint("user_id", "type", name="uq_chats_user_type"),)
```

- `user_id` is the *customer*. There is no `support_user_id`: any support agent can pick up any chat.
- The unique constraint enforces "one main + one sidequest per user" at the DB level.

### `messages` — new

```python
class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid_pk]
    chat_id: Mapped[UUID] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)            # "user" | "support"
    kind: Mapped[str] = mapped_column(String(20), nullable=False)            # "message" | "file"
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_id: Mapped[UUID | None] = mapped_column(ForeignKey("chat_files.id"), nullable=True)
    client_msg_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[created_at]

    __table_args__ = (
        Index("ix_messages_chat_created", "chat_id", "created_at"),
        Index(
            "uq_messages_chat_client_msg_id",
            "chat_id", "client_msg_id",
            unique=True,
            postgresql_where=text("client_msg_id IS NOT NULL"),
        ),
    )
```

- No `updated_at` — messages are immutable in v1 (no edit/delete).
- `role` is denormalized to match Go's canonical Message shape and avoid joining `users` on every history fetch.
- The partial unique index on `(chat_id, client_msg_id)` makes the internal POST endpoint idempotent: if Go retries because its HTTP call to Python timed out, Python returns the same row instead of inserting a duplicate.

### `chat_files` — new

```python
class ChatFile(Base, TimestampMixin):
    __tablename__ = "chat_files"

    id: Mapped[uuid_pk]                                                                       # this is the file_id seen by Go and clients
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)     # uploader
    chat_id: Mapped[UUID] = mapped_column(ForeignKey("chats.id"), nullable=False)             # scoped to one chat (ACL)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime: Mapped[str] = mapped_column(String(127), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending") # pending | uploaded | linked
    object_key: Mapped[str] = mapped_column(String(255), nullable=False)                       # "chats/{chat_id}/{file_id}/{name}"

    __table_args__ = (Index("ix_chat_files_user_status", "user_id", "status"),)
```

- `chat_id` on `chat_files` binds a file to one chat at upload time. Sending it in another chat is rejected. Prevents file_id leakage between chats.
- `status` lifecycle: `pending` (created, awaiting upload) → `uploaded` (client confirmed; size verified via MinIO HEAD inside the confirm handler) → `linked` (referenced by a message). Transitions are forward-only.
- `object_key` template `chats/{chat_id}/{file_id}/{name}` namespaces files by chat and prevents key collisions.

### Constants shared with Go and frontend

| | Value |
|---|---|
| Chat types | `"main"`, `"sidequest"` |
| Message roles | `"user"`, `"support"` |
| Message kinds | `"message"`, `"file"` |
| Internal-secret header | `X-Internal-Secret` |
| File ID format | UUID v4 string |

These are module-level constants in `app/services/chat_service.py`. Frontend depends on the JSON tag names — do not rename without coordinating across the stack.

### Migrations

Three Alembic migrations, in order:

1. **`0001_baseline`** — declares the current `users` and `refresh_tokens` tables. Idempotent: if tables already exist (created by SQLAlchemy `create_all` in dev), the migration is a no-op that only stamps `alembic_version`. Bootstraps Alembic for the project.
2. **`0002_add_role_login_to_users`** — `ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'user'` and `ADD COLUMN login VARCHAR(64) UNIQUE`. Postgres applies the default to existing rows in one statement.
3. **`0003_chat_domain`** — creates `chats`, `messages`, `chat_files` with all indexes, foreign keys, and the partial unique index on `messages(chat_id, client_msg_id)`. Enables the `pgcrypto` extension at the top (`CREATE EXTENSION IF NOT EXISTS pgcrypto`). Includes a data migration at the bottom:

```python
op.execute("""
    INSERT INTO chats (id, user_id, type, created_at, updated_at)
    SELECT gen_random_uuid(), u.id, t.type, now(), now()
    FROM users u CROSS JOIN (VALUES ('main'), ('sidequest')) AS t(type)
    ON CONFLICT (user_id, type) DO NOTHING;
""")
```

Migrations are forward-only. `downgrade()` bodies are the autogenerated `drop_table` calls; we do not promise to rollback prod.

---

## 5. API surface

### 5.1 Internal endpoints (Go → Python)

Mounted at `/internal/*` on the FastAPI app directly (not under `/api/v1`, matching Go's expectations). Both endpoints require the `X-Internal-Secret: <CHATGW_INTERNAL_SECRET>` header via the `internal_secret` router-level dependency. Missing/wrong secret → `403`.

#### `POST /internal/auth/ws-validate`

Called by Go once per WebSocket upgrade.

```json
// Request
{
  "token": "<JWT>",
  "chat_type": "main" | "sidequest",
  "chat_id_hint": "<UUID>" | ""
}

// 200 Response
{
  "user_id": "42",          // stringified to match Go's string ID type
  "role": "user" | "support",
  "chat_id": "<UUID>"
}
```

Logic:

1. Validate JWT (signature + expiry). On failure → `401`.
2. Read `user_id` and `role` from the token. If `role` claim is absent, default to `"user"` (backward compatibility for tokens issued before this change).
3. Resolve `chat_id`:
   - `role=user`: look up the user's chat with the requested `type`. Must exist (guaranteed by registration + backfill). If not, `404`.
   - `role=support`: `chat_id_hint` must be present and must reference an existing chat of the requested `type`. If missing or mismatched → `400`.
4. Return `{user_id (stringified), role, chat_id}`.

#### `POST /internal/chats/{chat_id}/messages`

Called by Go after each validated inbound WS frame.

```json
// Request
{
  "user_id": "42",
  "role": "user" | "support",
  "kind": "message" | "file",
  "body": "...",            // when kind="message"
  "file_id": "<UUID>",      // when kind="file"
  "client_msg_id": "<UUID>" // optional but recommended
}

// 200 Response: canonical Message matching Go's struct
{
  "id": "<UUID>",
  "chat_id": "<UUID>",
  "user_id": "42",
  "role": "user",
  "kind": "message",
  "body": "...",
  "file": null,             // or { "file_id", "name", "mime", "size", "url" } when kind="file"
  "client_msg_id": "...",
  "created_at": "2026-05-19T..."
}
```

Logic:

1. If `client_msg_id` is set, look up `(chat_id, client_msg_id)`. If a row exists, return that row (idempotent retry).
2. Validate:
   - `kind="message"`: `body` non-empty, within `message_max_body_bytes`.
   - `kind="file"`: `file_id` references a `chat_files` row with `status="uploaded"`, `user_id` matches sender, `chat_id` matches the URL param. Otherwise `400`.
3. Within one transaction: insert `messages` row; if file, update `chat_files.status` to `"linked"`.
4. Build the response: for `kind="file"`, generate a fresh presigned GET URL (7-day TTL) and embed it as `file.url`.

### 5.2 Support auth (new router, `/api/v1/auth/support/`)

#### `POST /api/v1/auth/support/login/`

```json
// Request
{ "login": "alice", "password": "..." }

// 200 Response: same TokenResponse shape used by the existing /auth endpoints
{ "access_token": "...", "refresh_token": "...", "token_type": "bearer", "user": { ... } }
```

- Looks up the User by `login` where `role='support'`, verifies password against `password_hash`.
- Issues an access token with `role="support"` claim and a refresh token (reused mechanism).
- Refresh and logout for support reuse the existing `/api/v1/auth/refresh/` and `/api/v1/auth/logout/` — refresh tokens are opaque and role-agnostic in the DB; the role is read from the User row at refresh time.

### 5.3 Public chat endpoints (`/api/v1/chats/`)

Existing route signatures stay; some response shapes get enriched.

| Method | Path | Behavior in v1 |
|---|---|---|
| `GET /chats/` | List chats | `role=user`: returns the caller's two chats. `role=support`: returns all chats, paginated `?limit=&cursor=`, sorted by latest activity desc, optional `?type=`. Each item includes counterpart info, last message preview, last activity timestamp, and `unread_count` (always 0 in v1 — see Section 11). |
| `POST /chats/` | "Create" chat | Becomes idempotent get-by-type: returns the caller's existing chat for the requested type. Customers don't need this (auto-created at registration); preserved for frontend compatibility. |
| `GET /chats/{chat_id}/messages/` | List messages | Cursor-based pagination `?limit=50&before=<msg_id>`. Returns messages newest-first. For `kind="file"` messages, embeds a fresh presigned GET URL. Authz: caller must be participant (user owns chat OR caller is support). |
| `POST /chats/{chat_id}/messages/` | Send via REST | **`not_implemented`** — the channel is WS via Go. Out of scope. |
| `POST /chats/{chat_id}/read/` | Mark read | **`not_implemented`** — read tracking requires extra schema; punted. |
| `GET /chats/{chat_id}/files/` | List files in chat | Returns `chat_files` rows for the chat with status `linked` or `uploaded`, including fresh presigned GET URLs. Response shape changes from `list[str]` to `list[FileMeta]`. |

#### Enriched DTOs

```python
class CounterpartInfo(BaseModel):
    user_id: int                           # for user: a synthetic support id (e.g., 0) since "any support"
    display_name: str                      # for user: "Support"; for support: customer's first_name + last_name
    role: str                              # "user" | "support"

class MessagePreview(BaseModel):
    kind: str                              # "message" | "file"
    body_preview: str | None               # truncated to ~120 chars; None when kind="file"
    file_name: str | None                  # populated when kind="file"
    created_at: datetime

class ChatListItem(BaseModel):
    id: UUID
    type: str                              # "main" | "sidequest"
    counterpart: CounterpartInfo
    last_message: MessagePreview | None
    last_activity_at: datetime | None      # max(messages.created_at) for this chat; None if no messages
    unread_count: int = 0                  # always 0 in v1 — kept in shape for forward compat

class FileMeta(BaseModel):
    file_id: UUID
    name: str
    mime: str
    size: int
    url: str                               # fresh presigned GET URL
```

**Pagination cursor formats:**

- `GET /chats/?cursor=<token>` — `token` is base64url-encoded JSON `{"last_activity_at": "<ISO>", "id": "<UUID>"}`. Lookup is `WHERE (last_activity_at, id) < (cursor.last_activity_at, cursor.id)`.
- `GET /chats/{chat_id}/messages/?before=<msg_id>` — `before` is a raw message UUID. Lookup is `WHERE created_at < (SELECT created_at FROM messages WHERE id = $before)`. Simpler than chat-list pagination because messages have a hard chronological ordering within one chat.

### 5.4 Files endpoints (new router, `/api/v1/files/`)

| Method | Path | Behavior |
|---|---|---|
| `POST /files/` | Request upload | Input: `{chat_id, name, mime, size}`. Validates participant, mime allowlist (if enabled), size limit. Creates `chat_files` row with `status="pending"`, generates presigned PUT URL. Returns `{file_id, upload_url, upload_method: "PUT", upload_headers: {...}, expires_at}`. |
| `POST /files/{file_id}/confirm/` | Confirm upload | Caller must own the file. Issues a MinIO HEAD on the object; `404` if missing, `400` if size mismatches. Flips row to `status="uploaded"`. Idempotent on already-uploaded rows. |
| `GET /files/{file_id}/` | Get FileMeta | Returns `{file_id, name, mime, size, url}` with a fresh presigned GET URL. Authz: caller must be participant of the file's chat. Used for refreshing expired URLs. |

---

## 6. Critical flows

### 6.1 WebSocket connect & validate

```
Client                Go (chatgw)              Python (/internal)              Postgres
  │  ws://...?type=main           │                            │
  │  Sec-WebSocket-Protocol:      │                            │
  │    chatgw.token.<JWT>,chatgw.v1                            │
  │──────────────────────────────►│                            │
  │                               │  POST /internal/auth/ws-validate
  │                               │  X-Internal-Secret: <secret>
  │                               │  { token, chat_type, chat_id_hint }
  │                               │───────────────────────────►│
  │                               │                            │  jwt.decode → user_id, role
  │                               │                            │  SELECT chats WHERE
  │                               │                            │    user_id=$1 AND type=$2   (role=user)
  │                               │                            │   OR id=$hint AND type=$2  (role=support)
  │                               │                            │───►[DB]
  │                               │   { user_id, role, chat_id }                  ◄────│
  │                               │◄───────────────────────────│
  │   WS 101 Switching Protocols  │                            │
  │◄──────────────────────────────│                            │
```

Failure branches Go cares about: `401` (token bad) → Go returns 401 pre-upgrade. `403` (internal-secret wrong) → Go returns 403 pre-upgrade. `400`/`404` → Go returns 403. `5xx` or timeout (3s) → Go returns 500.

### 6.2 Client sends a text message

```
Client          Go (chatgw)              Python                     Postgres
  │  WS frame:                │                            │
  │  { type:"send_message", body, client_msg_id }
  │──────────────────────────►│                            │
  │                           │  validate frame size, schema
  │                           │  POST /internal/chats/{chat_id}/messages
  │                           │  X-Internal-Secret
  │                           │  { user_id, role, kind:"message", body, client_msg_id }
  │                           │───────────────────────────►│
  │                           │                            │  idempotency check:
  │                           │                            │  SELECT WHERE chat_id, client_msg_id
  │                           │                            │───►[DB]   (hit? return existing)
  │                           │                            │
  │                           │                            │  validate body length, kind
  │                           │                            │  INSERT INTO messages ...
  │                           │                            │───►[DB]
  │                           │   Message {...}                                  │
  │                           │◄───────────────────────────│
  │                           │  Hub.Publish(chat_id, msg)
  │                           │     → fans out to every WS in this chat (sender + counterpart)
  │   WS frame: { type:"message", message: {...} }
  │◄──────────────────────────│                            │
```

**Idempotency contract:** Go has a 5s HTTP timeout to Python. If Go's TCP connection drops after Python committed but before Go got the response, Go retries with the same `client_msg_id`. The partial unique index plus the explicit pre-check means Python returns the same row instead of inserting a duplicate.

Validation failures (Python returns `400` with `{detail, code}`): empty `body`, `body` exceeds `message_max_body_bytes`, unknown `kind`. Go translates these to a WS `error` frame to the offending sender only — never broadcast.

### 6.3 File upload lifecycle

```
Client                     Python (/api/v1/files)             MinIO                Postgres
  │  ① POST /files/                                                          │
  │  { chat_id, name, mime, size }                                          │
  │────────────────────────────►│                                          │
  │                              │  authz: caller is participant of chat_id
  │                              │  validate mime allowlist, size ≤ limit
  │                              │  INSERT chat_files(status='pending',
  │                              │    object_key="chats/{chat_id}/{file_id}/{name}")
  │                              │───────────────────────────────────────────────►[DB]
  │                              │  presign PUT URL via boto3
  │                              │───────────────────►│                    │
  │                              │     <signed URL>   │                    │
  │  { file_id, upload_url, expires_at, headers }                          │
  │◄─────────────────────────────│                                          │
  │                                                                         │
  │  ② PUT upload_url   (bytes go straight to MinIO — bypass Python)       │
  │──────────────────────────────────►│                                    │
  │                                              201 Created
  │◄──────────────────────────────────│
  │                                                                         │
  │  ③ POST /files/{file_id}/confirm                                       │
  │────────────────────────────►│                                          │
  │                              │  authz: caller owns file row
  │                              │  HEAD object in MinIO
  │                              │───────────────────►│                    │
  │                              │  size, etag        │                    │
  │                              │◄───────────────────│                    │
  │                              │  verify size matches declared
  │                              │  UPDATE chat_files SET status='uploaded'
  │                              │───────────────────────────────────────────────►[DB]
  │  200 OK                      │                                          │
  │◄─────────────────────────────│                                          │
```

The HEAD in step ③ is the only time Python touches MinIO during upload, and it's outside the message hot path. After ③ returns, the file is ready to be referenced by a WS `send_file` frame.

### 6.4 Client sends a file message

```
Client          Go (chatgw)              Python                     MinIO              Postgres
  │  WS frame: { type:"send_file", file_id, client_msg_id }
  │──────────────────────────►│                            │
  │                           │  POST /internal/chats/{chat_id}/messages
  │                           │  { user_id, role, kind:"file", file_id, client_msg_id }
  │                           │───────────────────────────►│                    │
  │                           │                            │  idempotency check
  │                           │                            │  validate:
  │                           │                            │    chat_files WHERE id=$file_id
  │                           │                            │    AND user_id=$sender
  │                           │                            │    AND chat_id=$chat_id
  │                           │                            │    AND status='uploaded'
  │                           │                            │───►[DB]
  │                           │                            │  BEGIN
  │                           │                            │  INSERT messages(kind='file', file_id=...)
  │                           │                            │  UPDATE chat_files SET status='linked'
  │                           │                            │  COMMIT
  │                           │                            │───►[DB]
  │                           │                            │  presign GET URL (7-day TTL)
  │                           │                            │───────────────►│
  │                           │                            │   <signed url> │
  │                           │   Message { kind:"file", file:{...}}        │
  │                           │◄───────────────────────────│                │
  │                           │  Hub.Publish → fanout
  │   WS frame: { type:"file", message: {...} }
  │◄──────────────────────────│                            │
```

Each `file_id` lands in exactly one message, ever. A file in `pending` can't be sent. A file in `linked` was already used — sending it again is `400`.

---

## 7. Auth, secrets, and config

### 7.1 JWT claim changes

Existing payload: `{user_id, type: "access", exp, iat}`. New payload adds a `role` claim:

```python
# app/services/auth_service.py
def _generate_access_token(self, user_id: int, role: str = "user") -> str:
    payload = {"user_id": user_id, "role": role, "type": "access", "exp": ..., "iat": ...}
```

Three call sites in `AuthService` pass `user.role` instead of taking the default. Token-generation and refresh-token helpers are promoted to module-level functions so `SupportAuthService` can reuse them without duplicating logic; the existing class methods become 1-line passthroughs. No caller of `AuthService` changes.

The `role` claim is read by ws-validate. If absent (tokens issued before this rollout), it defaults to `"user"` — backward compatible.

### 7.2 Support login service

`app/services/support_auth_service.py`:

```python
class SupportAuthService:
    def __init__(self, session): self._session = session

    async def login(self, login: str, password: str) -> TokenResponse:
        user = await session.execute(
            select(User).where(User.login == login, User.role == "support")
        ).scalar_one_or_none()
        if not user or not pwd_context.verify(password, user.password_hash):
            raise ValueError("Invalid credentials")     # generic — no leak on which factor failed
        access = make_access_token(user.id, user.role)
        refresh = await create_refresh_token(self._session, user.id)
        return TokenResponse(access_token=access, refresh_token=refresh.token, ...)
```

Refresh and logout reuse existing endpoints. If a support agent is demoted to `user`, their next refresh issues a customer-grade access token; their current access token still claims `role=support` until it expires (≤15 min). v1 accepts this delay.

### 7.3 Internal-secret dependency

`app/api/dependencies/internal_secret.py`:

```python
INTERNAL_SECRET_HEADER = "X-Internal-Secret"

async def require_internal_secret(
    x_internal_secret: str = Header(default="", alias=INTERNAL_SECRET_HEADER),
):
    expected = settings.internal_secret
    if not expected:
        raise HTTPException(500, "internal secret not configured")
    if not secrets.compare_digest(x_internal_secret, expected):
        raise HTTPException(403, "forbidden")
```

- `secrets.compare_digest` — constant-time comparison.
- Configured-but-empty value treated as a server error, not silent allow-all.
- Mounted as a router-level dependency on the entire `internal_router`. Impossible to forget on a per-handler basis.

### 7.4 Config additions (`app/core/config.py`)

```python
internal_secret: str = ""                                  # MUST be set; empty triggers 500 on every internal call
minio_endpoint: str = "minio:9000"
minio_access_key: str = "minioadmin"
minio_secret_key: str = "minioadmin"
minio_bucket: str = "chat-files"
minio_use_ssl: bool = False
minio_presign_put_expires_seconds: int = 600              # 10 min
minio_presign_get_expires_seconds: int = 7 * 24 * 3600    # 7 days — MinIO max for v4 signatures
file_max_size_bytes: int = 25 * 1024 * 1024               # 25 MiB
file_mime_allowlist: list[str] = []                       # empty = allow all; non-empty = exact match
message_max_body_bytes: int = 32768                       # matches Go's CHATGW_MAX_MESSAGE_BYTES default
```

### 7.5 MinIO client

`app/core/minio.py`:

```python
from aioboto3 import Session

_session = Session()

def s3_client():
    return _session.client(
        "s3",
        endpoint_url=f"{'https' if settings.minio_use_ssl else 'http'}://{settings.minio_endpoint}",
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        region_name="us-east-1",   # required by signing, ignored by MinIO
    )
```

Used as `async with s3_client() as s3: ...` per operation.

A startup hook (in `app/main.py`'s `lifespan`) calls a helper that creates the bucket if it doesn't exist (idempotent).

### 7.6 CLI seeder

`app/scripts/create_support_user.py`:

```bash
uv run python -m app.scripts.create_support_user \
  --login alice --email alice@example.com --phone +10000000000 --password 'changeme'
```

- Inserts a `User` row with `role="support"`, the provided `login`, `password_hash = pwd_context.hash(password)`, and required `email`/`phone` (the `phone` is a contact field — not an SMS-auth target for support users).
- Idempotent on `login`: if a user with that login already exists, `--reset-password` updates the hash; without that flag, errors out.
- Also seeds bonuses + deals chats for the new support user (keeps the invariant "every users row has its two chats" universally true; ws-validate never special-cases support).

### 7.7 Auth boundary summary

| Surface | Auth |
|---|---|
| `/api/v1/auth/*` (customer SMS) | unchanged |
| `/api/v1/auth/support/login/` | login + password against `users` where `role='support'` |
| `/api/v1/auth/refresh/`, `/auth/logout/` | unchanged, works for both roles |
| `/api/v1/chats/*`, `/api/v1/files/*` | JWT in `Authorization: Bearer <token>`, role read from claim |
| `/internal/*` | `X-Internal-Secret` header only (no JWT; Go presents the user's JWT inside the body) |

---

## 8. Infrastructure

### 8.1 `docker-compose.yml` additions

```yaml
services:
  # ... existing services unchanged ...

  minio:
    image: minio/minio:latest
    container_name: minio
    networks: [net]
    env_file: [.env]
    ports:
      - "9000:9000"
      - "9001:9001"
    command: server /data --console-address ":9001"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 10s
      timeout: 5s
      retries: 5
    volumes:
      - minio_data:/data
    restart: unless-stopped

  minio-init:
    image: minio/mc:latest
    container_name: minio-init
    networks: [net]
    depends_on:
      minio:
        condition: service_healthy
    env_file: [.env]
    entrypoint: >
      /bin/sh -c "
      mc alias set local http://minio:9000 $$MINIO_ROOT_USER $$MINIO_ROOT_PASSWORD &&
      mc mb --ignore-existing local/$$MINIO_BUCKET
      "

volumes:
  postgres_data:
  redis_data:
  minio_data:
```

The `app` consumes MinIO via the internal docker network (`endpoint_url=http://minio:9000`). Host-mapped `9000` is for dev tools; the app does not go through `localhost`.

### 8.2 `.env` additions

```bash
INTERNAL_SECRET=<long random string>

MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=<long random string>
MINIO_BUCKET=chat-files

MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=${MINIO_ROOT_USER}
MINIO_SECRET_KEY=${MINIO_ROOT_PASSWORD}
MINIO_USE_SSL=false
```

A `.env.example` (committed) documents every required key. Real `.env` stays gitignored.

### 8.3 `pyproject.toml` additions

```toml
[project]
dependencies = [
  # ... existing ...
  "alembic>=1.13.0",
  "aioboto3>=12.0.0",
  "python-multipart>=0.0.9",
]

[dependency-groups]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.23",
  "httpx>=0.27",
  "freezegun>=1.4",
]
```

`aioboto3` pulls in `aiobotocore` and `boto3` transitively.

### 8.4 Alembic bootstrap

```
InsurancePlatformPy/
  alembic.ini
  alembic/
    env.py
    script.py.mako
    versions/
      0001_baseline.py
      0002_add_role_login_to_users.py
      0003_chat_domain.py
```

- `alembic.ini`: `script_location = alembic`, `sqlalchemy.url` resolved at runtime via env (`env.py` reads `DATABASE_URL`).
- `env.py`: async-aware (uses `asyncpg`); imports `Base.metadata` from `app/models/base.py`; walks every module under `app/models/tables/` to register tables for autogenerate.

### 8.5 Run-the-system checklist (fresh dev)

```bash
cd InsurancePlatformPy
cp .env.example .env                                          # fill in secrets
docker compose up -d database redis minio minio-init          # infra first
docker compose run --rm alembic                               # migrate
uv run python -m app.scripts.create_support_user \
    --login alice --email alice@example.com \
    --phone +10000000000 --password 'changeme'                # seed a support user
docker compose up app                                          # FastAPI on :8000

# In a separate terminal:
cd ../InsurancePlatform
CHATGW_PYTHON_BASE_URL=http://localhost:8000 \
CHATGW_INTERNAL_SECRET="$(grep ^INTERNAL_SECRET ../InsurancePlatformPy/.env | cut -d= -f2)" \
go run ./cmd/chatgw                                            # Go on :8080
```

---

## 9. Error handling

### 9.1 Error response shape

```json
{ "detail": "<human-readable reason>", "code": "<machine_token>" }
```

`code` is added via a helper that wraps `HTTPException`. Existing endpoints without `code` are unaffected.

### 9.2 Reserved codes

Strings match Go's existing taxonomy (`internal/conn/envelope.go`).

| `code` | HTTP | When |
|---|---|---|
| `validation` | 400 | Bad input |
| `unauthorized` | 401 | JWT invalid/expired (ws-validate only) |
| `forbidden` | 403 | Internal-secret missing/wrong; caller not a participant |
| `not_found` | 404 | chat_id missing, file row missing, MinIO object missing on confirm |
| `payload_too_large` | 413 | Body or file exceeds limits |
| `unsupported_type` | 415 | File mime not in allowlist |
| `internal` | 500 | DB error, MinIO transport error, unhandled exception |
| `rate_limited` | 429 | Reserved for future |

### 9.3 Per-endpoint failure matrix

**`POST /internal/auth/ws-validate`**

| Condition | Status | code |
|---|---|---|
| `X-Internal-Secret` mismatch | 403 | `forbidden` |
| JWT invalid/expired | 401 | `unauthorized` |
| `chat_type` not in `{main, sidequest}` | 400 | `validation` |
| `role=support` and `chat_id_hint` empty | 400 | `validation` |
| `role=support` and `chat_id_hint` wrong type / not found | 400 | `validation` |
| `role=user` and no chat row for `(user_id, type)` | 404 | `not_found` (anomaly — logged) |
| Token has `role=support` but user row says `role=user` | 401 | `unauthorized` |

**`POST /internal/chats/{chat_id}/messages`**

| Condition | Status | code |
|---|---|---|
| `X-Internal-Secret` mismatch | 403 | `forbidden` |
| chat_id missing | 404 | `not_found` |
| `kind` not in `{message, file}` | 400 | `validation` |
| `kind=message` and `body` empty | 400 | `validation` |
| `body` longer than `message_max_body_bytes` | 413 | `payload_too_large` |
| `kind=file` and `file_id` missing | 400 | `validation` |
| `file_id` missing / wrong owner / wrong chat | 400 | `validation` |
| `file_id` status `pending` | 400 | `validation` (`"file not uploaded yet"`) |
| `file_id` status `linked` | 400 | `validation` (`"file already attached"`) |
| Same `client_msg_id` already exists | 200 | returns existing row (not an error) |
| DB transient | 500 | `internal` |

**`POST /api/v1/files/`**

| Condition | Status | code |
|---|---|---|
| Caller not participant | 403 | `forbidden` |
| Declared `size` exceeds limit | 413 | `payload_too_large` |
| `mime` not in allowlist | 415 | `unsupported_type` |
| MinIO unreachable | 500 | `internal` |

**`POST /api/v1/files/{file_id}/confirm/`**

| Condition | Status | code |
|---|---|---|
| Caller doesn't own file | 403 | `forbidden` |
| MinIO HEAD returns NoSuchKey | 404 | `not_found` |
| MinIO size mismatch | 400 | `validation` |
| Already `uploaded` or `linked` | 200 | no-op (idempotent) |

### 9.4 Go → WS error frame mapping

Go reads `error.code` from Python's 4xx body and emits, to the sender only (never broadcast):

```json
{ "type": "error", "error": { "code": "<code>", "reason": "<detail>", "ref": "<client_msg_id>" } }
```

`ref` is populated only when the original frame carried `client_msg_id`. This lets the React harness highlight specific failed messages.

### 9.5 Idempotency contract

| Where | How |
|---|---|
| Go → Python message persistence | Same `client_msg_id` returns the existing row, same `id`, same `created_at`. Partial unique index guards concurrent retries. |
| Client → Python confirm | Confirm on a row already `uploaded` or `linked` returns 200. Status only transitions forward. |
| MinIO bucket bootstrap | `minio-init` uses `mc mb --ignore-existing`; runs every `docker compose up`. |

### 9.6 Race conditions and outcomes

| Race | Outcome |
|---|---|
| User opens two tabs simultaneously, both hit ws-validate | Both succeed (chat row already exists from registration). No race. |
| Two clients submit `send_message` with same `client_msg_id` | Partial unique index — second insert raises `IntegrityError`; handler catches and re-reads. Both callers get the same Message back. |
| Client calls `/files/.../confirm` while a second tab is reading the same file | Confirm is idempotent. Read sees `pending` then `uploaded` — fine, no transactional read needed. |
| Support demoted to `user` mid-session | Existing access token still claims `role=support` until expiry (≤15 min). Refresh returns `role=user` from then on. |
| Client uploads file but never calls confirm | Row stays `pending`. Cleanup (cron deleting old `pending` rows) is out of scope. |

### 9.7 Logging conventions

All new modules use structured logging:

- `event` — `chat.message_inserted`, `file.presigned`, `internal.auth_failed`, etc.
- `chat_id`, `user_id`, `file_id` — relevant IDs when present.
- `caller_role` — `"user"` | `"support"` | `"internal"`.

Internal-secret failures, JWT decode failures, and 5xx responses log at WARN/ERROR. Successful internal calls log at DEBUG. Public endpoint successes use INFO.

PII never logged: phone numbers, file content, message bodies. `client_msg_id` and `file_id` are opaque UUIDs, safe to log.

---

## 10. Testing

### 10.1 Layout

```
InsurancePlatformPy/
  tests/
    conftest.py
    unit/
      test_chat_service.py
      test_file_service.py
      test_support_auth_service.py
      test_internal_token_service.py
    integration/
      test_internal_ws_validate.py
      test_internal_messages.py
      test_files_endpoints.py
      test_chats_endpoints.py
      test_support_auth_endpoints.py
    migrations/
      test_chat_domain_migration.py
  pytest.ini
```

### 10.2 Stack

- `pytest` + `pytest-asyncio` (`asyncio_mode = auto`).
- `httpx.AsyncClient` against the FastAPI app via `ASGITransport(app=app)` — in-process, no Uvicorn.
- Real Postgres on a separate test database (`insurance_platform_test`); Alembic-migrated in a session-scoped fixture; per-test isolation via savepoint rollback.
- Real MinIO, separate bucket `chat-files-test`.
- No mocking of internal seams; mock only the SMS provider and the clock (when testing TTLs).

### 10.3 Coverage targets

**Unit:**

| File | Coverage |
|---|---|
| `test_chat_service.py` | `ensure_user_chats` creates both rows idempotently; `resolve_chat_id` returns user's chat for `role=user`, hint-matched chat for `role=support`, rejects mismatched type. |
| `test_file_service.py` | `request_upload` inserts pending row + correct object_key; `confirm_upload` flips state and verifies MinIO HEAD size; presigned GET URL contains expected signature params. |
| `test_support_auth_service.py` | Wrong password → `ValueError`; wrong role → `ValueError`; success returns role-tagged JWT. |
| `test_internal_token_service.py` | Token without `role` defaults to `"user"`; expired raises; modified signature raises. |

**Integration:**

| File | Critical scenarios |
|---|---|
| `test_internal_ws_validate.py` | Bad secret → 403; bad JWT → 401; user resolves own chat; support requires `chat_id_hint`; wrong-type hint → 400; missing backfill → 404 (synthetic). |
| `test_internal_messages.py` | Text insert; duplicate `client_msg_id` returns same `id`; empty body → 400; oversize → 413; file happy path inserts message AND flips `chat_files.status` to `linked`; `pending` file_id → 400; other user's file_id → 400; cross-chat file_id → 400; already-`linked` file_id → 400. |
| `test_files_endpoints.py` | Non-participant → 403; presigned PUT URL accepts real upload to MinIO; confirm flips status; confirm on missing object → 404; confirm size mismatch → 400; mime allowlist enforcement. |
| `test_chats_endpoints.py` | User: 2 chats; Support: paginated list with counterpart info; history pagination cursor; non-participant → 403; presigned GET URLs in history return 200 on HEAD. |
| `test_support_auth_endpoints.py` | Wrong creds → 400 generic message; `role=user` user attempting support login → 400; issued JWT has `role=support`; refresh keeps `role=support`. |

**Migration:** `test_chat_domain_migration.py` runs Alembic upgrade against a fresh DB, inserts pre-existing users *before* the chat-domain migration, asserts every existing user has exactly 2 chat rows after.

### 10.4 End-to-end smoke

Not automated in v1 (Go lives in a sibling repo). Documented checklist in `tests/README.md`:

1. `docker compose up` everything.
2. Seed a support user via CLI.
3. Register a customer.
4. Start Go with both env vars.
5. React harness: customer sends text → support receives.
6. Support replies → customer receives.
7. Customer uploads file → support sees it rendered.
8. Force-disconnect Go, send a message, reconnect — assert ordering and no duplication.

### 10.5 Commands

```bash
uv run pytest tests/unit -q                  # fast unit-only

docker compose up -d database redis minio minio-init
uv run alembic upgrade head
uv run pytest -q                              # full suite
```

---

## 11. Out of scope (deliberate punts)

- **Read tracking and unread counts.** `POST /chats/{id}/read/` stays `not_implemented`. `unread_count` is in the response shape but always returns 0. Adding it requires `last_read_at` per chat (or a separate table) and corresponding update logic; future spec.
- **REST message send.** `POST /chats/{id}/messages/` stays `not_implemented`. The channel is WS via Go; REST send would require calling back into Go or duplicating broadcast logic.
- **Multi-instance Go.** Go's `Hub` interface anticipates Redis pub/sub for horizontal scale-out; Python's design doesn't constrain this either way. No change required here.
- **File cleanup.** Orphaned `pending` rows accumulate. A cron deleting them (and the corresponding MinIO objects) is future work.
- **Admin HTTP endpoints.** Support user management is via CLI only.
- **Typing indicators, presence, read receipts.** Out of scope for both Go (per its `todo.md`) and Python.
- **CI configuration.** No `.github/workflows` exists yet. Test commands documented; CI wiring is future work.
- **Load/latency benchmarks.** The architecture choices (no MinIO call on the message hot path, direct-to-S3 uploads) are the performance story; measuring is future work.

---

## 12. Open questions / decisions to revisit

- **Module-level promotion of `make_access_token` / `create_refresh_token`.** Current plan: promote to module-level functions in `app/services/auth_service.py`, with the class methods becoming 1-line passthroughs. Alternative: duplicate the ~10 lines into `SupportAuthService`. The promotion is slightly more invasive (touches existing class) but avoids duplication. Default: promotion.
- **`pgcrypto` extension** is used by the chat-domain data migration (for `gen_random_uuid()`). Postgres 18 (per docker-compose) bundles it; needs `CREATE EXTENSION` privilege in the database role. The default `postgres` user has it; document if a least-privilege user is used in prod.
- **Presigned GET URL TTL of 7 days.** Long enough for chat history to render comfortably; expired URLs can be refreshed via `GET /files/{file_id}/`. Revisit if shorter TTL needed for compliance.
- **Chat ID generation in the data migration uses `gen_random_uuid()` (Postgres-side).** Application-generated UUIDs are used everywhere else. Two paths is mildly inconsistent; acceptable for a one-shot migration.

---

## Appendix: surfaces summary

| Category | Count | Notes |
|---|---|---|
| New internal endpoints | 2 | Behind shared secret, not under `/api/v1` |
| New support auth endpoints | 1 | `/api/v1/auth/support/login/` (refresh/logout reuse existing) |
| New files endpoints | 3 | `/api/v1/files/...` |
| Replaced public chat bodies | 4 | list chats, idempotent get-by-type, list messages, list files |
| Deliberately stubbed | 2 | `POST /chats/{id}/messages/`, `POST /chats/{id}/read/` |
| New DB tables | 3 | `chats`, `messages`, `chat_files` |
| Modified DB columns | 2 | `users.role`, `users.login` |
| New env vars | 8 | `INTERNAL_SECRET` + 7 MinIO vars. File/message limits have config defaults; override via env only if needed. |
| New docker-compose services | 2 | `minio`, `minio-init` |
| Migrations | 3 | Baseline, role/login, chat domain (with backfill) |
