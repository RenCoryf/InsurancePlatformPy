# Chat Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Python (FastAPI) server side that backs the existing Go `chatgw` WebSocket gateway — internal endpoints for Go, support/admin auth, chat & file public REST, MinIO file storage, plus a small comment-rename in the Go repo.

**Architecture:** Strictly additive on `InsurancePlatformPy`. Four new tables (`chats`, `messages`, `files`, `support_agents`). New routers (`internal`, `support`, `admin`, plus filling existing `chats.py` / `files.py` stubs). New auth dependencies for support / dual-role / admin-basic / internal-secret. MinIO bytes flow through Python (no presigned URLs). Existing user JWT issuance gains two additive claims (`sub`, `role`); no existing claim is removed. Spec: `docs/superpowers/specs/2026-05-21-chat-server-design.md`.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 async + asyncpg, Pydantic v2 + pydantic-settings, Alembic, MinIO Python SDK, python-jose JWT, passlib bcrypt, pytest + pytest-asyncio + httpx ASGI transport.

---

## File map

### New files in `InsurancePlatformPy/`

```
app/
  api/
    routers/
      internal.py                  # /internal/auth/ws-validate, /internal/chats/{id}/messages
      support.py                   # /api/v1/support/login/, /api/v1/support/chats/
      admin.py                     # /api/v1/admin/support-agents/*
    deps/                          # NEW sub-package — keeps dependencies.py untouched
      __init__.py
      support_auth.py              # get_current_support
      subject_auth.py              # get_current_subject
      admin_auth.py                # admin_basic_auth
      internal_secret.py           # internal_secret_required
  models/
    tables/
      chat.py
      message.py
      file.py
      support_agent.py
    dto/
      chat.py
      message.py
      file.py
      support_agent.py
      internal.py
  repositories/
    chat_repository.py
    message_repository.py
    file_repository.py
    support_agent_repository.py
  services/
    chat_service.py
    file_service.py
    support_auth_service.py
    internal_service.py
    errors.py                      # ChatError exception
  core/
    minio_client.py
alembic.ini
alembic/
  env.py
  script.py.mako
  versions/
    20260521_0001_chat_domain.py
tests/
  conftest.py
  __init__.py
  unit/__init__.py
  unit/test_subject_parsing.py
  integration/__init__.py
  integration/test_internal_ws_validate.py
  integration/test_internal_messages.py
  integration/test_chats_public.py
  integration/test_files.py
  integration/test_support_login.py
  integration/test_support_chats.py
  integration/test_admin_support_agents.py
  integration/test_validation_envelope.py
.env.example                       # documents required env vars (gitignored .env stays gitignored)
pytest.ini
```

### Edited existing files

| File | Change |
|---|---|
| `pyproject.toml` | Add runtime deps (alembic, minio, python-multipart); add `[dependency-groups] dev` with pytest, pytest-asyncio. |
| `app/core/config.py` | Add fields: `internal_secret`, `max_message_bytes`, `max_file_bytes`, `minio_*`, `admin_login`, `admin_password`. |
| `app/main.py` | Add MinIO client init in `lifespan`; include new routers (`internal`, `support`, `admin`). The new internal router mounts directly on `app` (no `/api/v1` prefix); support and admin mount under `api_router`. |
| `app/api/main_router.py` | Add `include_router(support_router)` and `include_router(admin_router)`. |
| `app/api/routers/chats.py` | Replace `not_implemented()` bodies for `GET /chats/`, `POST /chats/`, `GET /chats/{chat_id}/messages/`. Drop `POST /chats/{chat_id}/messages/`, `POST /chats/{chat_id}/read/`, `GET /chats/{chat_id}/files/`. |
| `app/api/routers/files.py` | Replace `POST /files/presign/` and `GET /files/{file_id}/` (metadata) with `POST /files/` (multipart upload) and `GET /files/{file_id}/` (streaming download). |
| `app/services/auth_service.py` | In `_generate_access_token`, add `sub: f"user:{user_id}"` and `role: "user"` to the JWT payload alongside existing `user_id`. |

### Edited files in `InsurancePlatform/` (Go repo, companion commit)

| File | Change |
|---|---|
| `internal/auth/identity.go` | Comment `// "main" | "sidequest"` → `// "main" | "bonus"` |
| `internal/auth/client.go` | Doc comment `"chat_type": "main|sidequest"` → `"chat_type": "main|bonus"` |
| `internal/server/ws_handler.go` | Doc comment `"main" | "sidequest"` → `"main" | "bonus"` |
| `docs/frontend-integration.ru.md` | Two lines: `sidequest` → `bonus` |

---

## Phase 0 — Bootstrap

### Task 0.1: Add runtime dependencies

**Files:** Modify `pyproject.toml`

- [ ] **Step 1: Read current `pyproject.toml`**

Run: `cat pyproject.toml`
Confirm: current deps list ends before any `[tool.*]` sections.

- [ ] **Step 2: Add deps via `uv add`**

Run:
```bash
uv add alembic minio python-multipart
```
Expected: `uv` updates `pyproject.toml` and `uv.lock`. Adds three new lines under `dependencies`.

- [ ] **Step 3: Add dev deps**

Run:
```bash
uv add --dev pytest pytest-asyncio
```
Expected: creates `[dependency-groups] dev` with the new entries. `httpx` is already a runtime dep — tests can use it from there, no need to duplicate it into dev. The anyio plugin ships inside `anyio` itself (transitive via httpx/fastapi); there's no separate `pytest-anyio` package on PyPI worth installing.

- [ ] **Step 4: Verify**

Run:
```bash
uv sync && uv run python -c "import alembic, minio, pytest; print('ok')"
```
Expected output: `ok`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add alembic, minio, multipart, pytest"
```

### Task 0.2: pytest.ini and tests scaffold

**Files:**
- Create: `pytest.ini`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/conftest.py` (skeleton; expanded later)

- [ ] **Step 1: Write `pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
```

- [ ] **Step 2: Create empty package files**

```bash
touch tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py
```

- [ ] **Step 3: Write minimal `tests/conftest.py`**

```python
"""Test fixtures. Expanded in later phases."""

import pytest


@pytest.fixture
def hello():
    return "world"
```

- [ ] **Step 4: Add a smoke test to verify pytest is wired**

Create `tests/unit/test_smoke.py`:
```python
def test_pytest_runs(hello):
    assert hello == "world"
```

- [ ] **Step 5: Run the smoke test**

Run: `uv run pytest tests/unit/test_smoke.py -v`
Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add pytest.ini tests/
git commit -m "tests: scaffold pytest with smoke test"
```

### Task 0.3: Add new config fields

**Files:** Modify `app/core/config.py`

- [ ] **Step 1: Read current config**

Run: `cat app/core/config.py`
Confirm: `class Settings(BaseSettings):` exists, with the `model_config = SettingsConfigDict(env_file=".env", ...)`.

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_config.py`:
```python
from app.core.config import settings


def test_chat_config_defaults():
    # These attributes must exist with sensible defaults.
    assert settings.max_message_bytes == 64_000
    assert settings.max_file_bytes == 25_000_000
    assert settings.minio_bucket == "chat-files"
    assert settings.minio_secure is False


def test_chat_config_secrets_have_defaults_for_dev():
    # Defaults allow `pytest` to import without a .env file. Prod must override.
    assert settings.internal_secret == "dev-internal-secret-change-me"
    assert settings.admin_login == "admin"
    assert settings.admin_password == "admin"
    assert settings.minio_endpoint == "minio:9000"
    assert settings.minio_access_key == "minioadmin"
    assert settings.minio_secret_key == "minioadmin"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'max_message_bytes'`.

- [ ] **Step 4: Add config fields**

Edit `app/core/config.py`. After the existing `referral_link_base_url` line, add:

```python
    # Chat / file / admin / MinIO config (added 2026-05-21)
    internal_secret: str = "dev-internal-secret-change-me"
    max_message_bytes: int = 64_000
    max_file_bytes: int = 25_000_000

    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "chat-files"
    minio_secure: bool = False

    admin_login: str = "admin"
    admin_password: str = "admin"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add app/core/config.py tests/unit/test_config.py
git commit -m "config: add chat/minio/admin env settings"
```

### Task 0.4: `.env.example`

**Files:** Create `.env.example`

- [ ] **Step 1: Write `.env.example`**

```bash
# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=insurance_platform
DB_USER=postgres
DB_PASSWORD=postgres

# JWT
JWT_SECRET_KEY=your-secret-key-change-in-production-min-32-chars
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=15
JWT_REFRESH_TOKEN_EXPIRE_DAYS=30

# Chat (new in 2026-05-21 design)
INTERNAL_SECRET=change-me-to-a-long-random-string
MAX_MESSAGE_BYTES=64000
MAX_FILE_BYTES=25000000

# MinIO
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=chat-files
MINIO_SECURE=false

# Admin
ADMIN_LOGIN=admin
ADMIN_PASSWORD=change-me
```

- [ ] **Step 2: Verify `.env.example` is not gitignored**

Run: `git check-ignore .env.example && echo "IGNORED" || echo "OK to commit"`
Expected: `OK to commit`.

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "env: document required env vars in .env.example"
```

---

## Phase 1 — Alembic bootstrap

### Task 1.1: Initialize Alembic

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/` (directory)

- [ ] **Step 1: Run `alembic init`**

Run:
```bash
uv run alembic init alembic
```
Expected: creates `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/`, `alembic/README`.

- [ ] **Step 2: Replace `alembic/env.py`**

Overwrite `alembic/env.py` with:

```python
"""Alembic env — async-aware, reads DB URL from app settings."""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from app.core.config import settings
from app.models.base import Base

# Import every table module so Base.metadata is populated.
# Note: the canonical User and RefreshToken classes live under
# app.models.users.*, NOT app.models.tables.user / refresh_token
# (those exist as unused duplicates and collide on __tablename__ if
# imported alongside the canonical versions).
import app.models.users.entities  # noqa: F401   (User)
import app.models.users.refresh_token  # noqa: F401   (RefreshToken)
import app.models.tables.chat  # noqa: F401
import app.models.tables.message  # noqa: F401
import app.models.tables.file  # noqa: F401
import app.models.tables.support_agent  # noqa: F401


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

- [ ] **Step 3: Edit `alembic.ini`**

In `alembic.ini`, find `sqlalchemy.url =` and leave it blank (env.py sets it):

```ini
sqlalchemy.url =
```

Also confirm `script_location = alembic` is present (default).

- [ ] **Step 4: Verify the env.py imports won't fail later**

This step is a smoke check — the table modules don't exist yet, so we expect ModuleNotFoundError. Run:

```bash
uv run alembic check 2>&1 | head -5 || true
```
Expected: error like `ModuleNotFoundError: No module named 'app.models.tables.chat'`. This is correct — we'll add those modules in Phase 2.

- [ ] **Step 5: Commit**

```bash
git add alembic.ini alembic/
git commit -m "alembic: bootstrap async env"
```

---

## Phase 2 — Data model

### Task 2.1: `support_agents` table model

**Files:**
- Create: `app/models/tables/support_agent.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_models.py`:

```python
"""Smoke tests that the new ORM models import and have the expected columns."""

from sqlalchemy import inspect


def test_support_agent_columns():
    from app.models.tables.support_agent import SupportAgent

    cols = {c.name for c in inspect(SupportAgent).columns}
    assert cols == {
        "id", "login", "password_hash", "display_name", "is_active",
        "created_at", "updated_at",
    }
    assert SupportAgent.__tablename__ == "support_agents"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_models.py::test_support_agent_columns -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `app/models/tables/support_agent.py`**

```python
from sqlalchemy import String, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, int_pk


class SupportAgent(Base, TimestampMixin):
    __tablename__ = "support_agents"

    id: Mapped[int_pk]
    login: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_models.py::test_support_agent_columns -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add app/models/tables/support_agent.py tests/unit/test_models.py
git commit -m "model: support_agents table"
```

### Task 2.2: `chats` table model

**Files:**
- Create: `app/models/tables/chat.py`

- [ ] **Step 1: Append failing test to `tests/unit/test_models.py`**

```python
def test_chat_columns():
    from app.models.tables.chat import Chat

    cols = {c.name for c in inspect(Chat).columns}
    assert cols == {
        "id", "owner_user_id", "type", "created_at", "last_message_at",
    }
    assert Chat.__tablename__ == "chats"
    constraints = {c.name for c in Chat.__table__.constraints if c.name}
    assert "uq_chats_owner_type" in constraints
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_models.py::test_chat_columns -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `app/models/tables/chat.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("owner_user_id", "type", name="uq_chats_owner_type"),
        CheckConstraint("type IN ('main', 'bonus')", name="ck_chats_type"),
        Index("ix_chats_last_message_at", "last_message_at", postgresql_using="btree"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_models.py::test_chat_columns -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add app/models/tables/chat.py tests/unit/test_models.py
git commit -m "model: chats table"
```

### Task 2.3: `files` table model

**Files:**
- Create: `app/models/tables/file.py`

- [ ] **Step 1: Append failing test**

In `tests/unit/test_models.py`, add:

```python
def test_file_columns():
    from app.models.tables.file import File

    cols = {c.name for c in inspect(File).columns}
    assert cols == {
        "id", "chat_id", "uploader_subject_type", "uploader_subject_id",
        "original_name", "mime_type", "size_bytes", "minio_key", "created_at",
    }
    assert File.__tablename__ == "files"
```

- [ ] **Step 2: Run test (fails)**

Run: `uv run pytest tests/unit/test_models.py::test_file_columns -v`
Expected: FAIL.

- [ ] **Step 3: Write `app/models/tables/file.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class File(Base):
    __tablename__ = "files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, index=True)
    uploader_subject_type: Mapped[str] = mapped_column(String(20), nullable=False)
    uploader_subject_id: Mapped[int] = mapped_column(nullable=False)
    original_name: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    minio_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("uploader_subject_type IN ('user', 'support')", name="ck_files_uploader_subject_type"),
    )
```

- [ ] **Step 4: Run test (passes)**

Run: `uv run pytest tests/unit/test_models.py::test_file_columns -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add app/models/tables/file.py tests/unit/test_models.py
git commit -m "model: files table"
```

### Task 2.4: `messages` table model

**Files:**
- Create: `app/models/tables/message.py`

- [ ] **Step 1: Append failing test**

```python
def test_message_columns():
    from app.models.tables.message import Message

    cols = {c.name for c in inspect(Message).columns}
    assert cols == {
        "id", "chat_id", "sender_subject_type", "sender_subject_id",
        "kind", "body", "file_id", "client_msg_id", "created_at",
    }
    assert Message.__tablename__ == "messages"
```

- [ ] **Step 2: Run test (fails)**

Run: `uv run pytest tests/unit/test_models.py::test_message_columns -v`
Expected: FAIL.

- [ ] **Step 3: Write `app/models/tables/message.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    sender_subject_type: Mapped[str] = mapped_column(String(20), nullable=False)
    sender_subject_id: Mapped[int] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("files.id", ondelete="RESTRICT"), nullable=True)
    client_msg_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("sender_subject_type IN ('user', 'support')", name="ck_messages_sender_subject_type"),
        CheckConstraint("kind IN ('message', 'file')", name="ck_messages_kind"),
        CheckConstraint(
            "(kind = 'message' AND body IS NOT NULL AND file_id IS NULL) OR "
            "(kind = 'file'    AND file_id IS NOT NULL AND body IS NULL)",
            name="ck_messages_kind_body_xor",
        ),
        Index(
            "uq_messages_chat_client_msg_id",
            "chat_id", "client_msg_id",
            unique=True,
            postgresql_where=text("client_msg_id IS NOT NULL"),
        ),
        Index("ix_messages_chat_created", "chat_id", "created_at", "id", postgresql_ops={"created_at": "DESC", "id": "DESC"}),
    )
```

- [ ] **Step 4: Run test (passes)**

Run: `uv run pytest tests/unit/test_models.py::test_message_columns -v`
Expected: 1 passed.

- [ ] **Step 5: Run the entire model test file**

Run: `uv run pytest tests/unit/test_models.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add app/models/tables/message.py tests/unit/test_models.py
git commit -m "model: messages table"
```

### Task 2.5: Baseline Alembic migration (existing users/refresh_tokens tables)

The pre-existing project never used Alembic, so a fresh dev DB has no `users` or `refresh_tokens` tables. Phase 2's chat-domain migration FKs into `users.id`, so we need a baseline migration first that declares the existing schema. This baseline mirrors the live ORM definitions in `app/models/users/entities.py` and `app/models/users/refresh_token.py`.

**Files:**
- Create: `alembic/versions/20260521_0000_baseline.py`

- [ ] **Step 1: Create the baseline migration**

Write `alembic/versions/20260521_0000_baseline.py`:

```python
"""baseline — existing users and refresh_tokens tables

Revision ID: 20260521_0000
Revises:
Create Date: 2026-05-21
"""

import sqlalchemy as sa
from alembic import op


revision = "20260521_0000"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=True),
        sa.Column("last_name", sa.String(100), nullable=True),
        sa.Column("patronymic", sa.String(100), nullable=True),
        sa.Column("balance", sa.Numeric(14, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("pending_balance", sa.Numeric(14, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("referral_code", sa.String(16), nullable=False, unique=True),
        sa.Column("referrer_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_users_referral_code", "users", ["referral_code"], unique=True)
    op.create_index("ix_users_referrer_id", "users", ["referrer_id"])

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("token", sa.String(500), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_refresh_tokens_token", "refresh_tokens", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_token", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index("ix_users_referrer_id", table_name="users")
    op.drop_index("ix_users_referral_code", table_name="users")
    op.drop_table("users")
```

- [ ] **Step 2: Commit**

```bash
git add alembic/versions/20260521_0000_baseline.py
git commit -m "migration: baseline users + refresh_tokens"
```

### Task 2.6: Chat domain Alembic migration

**Files:**
- Create: `alembic/versions/20260521_0001_chat_domain.py`

- [ ] **Step 1: Generate the migration scaffold**

Run:
```bash
uv run alembic revision --autogenerate -m "chat domain"
```
Expected: creates a file under `alembic/versions/`. Open it.

- [ ] **Step 2: Replace the generated file's `upgrade()` body**

The autogenerated file may not include all CHECK constraints / partial indexes correctly. Replace the entire revision file body with the deterministic version below. Keep the auto-generated `revision = "<hash>"`, `down_revision`, `branch_labels`, `depends_on` lines untouched. The new file path should be `alembic/versions/20260521_0001_chat_domain.py` — rename the autogenerated file to match.

```python
"""chat domain

Revision ID: <leave-as-generated>
Revises:
Create Date: 2026-05-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision = "20260521_0001"
down_revision = "20260521_0000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "support_agents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("login", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_support_agents_login", "support_agents", ["login"], unique=True)

    op.create_table(
        "chats",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("owner_user_id", "type", name="uq_chats_owner_type"),
        sa.CheckConstraint("type IN ('main', 'bonus')", name="ck_chats_type"),
    )
    op.create_index("ix_chats_owner_user_id", "chats", ["owner_user_id"])
    op.create_index("ix_chats_last_message_at", "chats", ["last_message_at"])

    op.create_table(
        "files",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("chat_id", UUID(as_uuid=True), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploader_subject_type", sa.String(20), nullable=False),
        sa.Column("uploader_subject_id", sa.Integer(), nullable=False),
        sa.Column("original_name", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("minio_key", sa.String(512), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("uploader_subject_type IN ('user', 'support')", name="ck_files_uploader_subject_type"),
    )
    op.create_index("ix_files_chat_id", "files", ["chat_id"])

    op.create_table(
        "messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("chat_id", UUID(as_uuid=True), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_subject_type", sa.String(20), nullable=False),
        sa.Column("sender_subject_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("file_id", UUID(as_uuid=True), sa.ForeignKey("files.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("client_msg_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("sender_subject_type IN ('user', 'support')", name="ck_messages_sender_subject_type"),
        sa.CheckConstraint("kind IN ('message', 'file')", name="ck_messages_kind"),
        sa.CheckConstraint(
            "(kind = 'message' AND body IS NOT NULL AND file_id IS NULL) OR "
            "(kind = 'file'    AND file_id IS NOT NULL AND body IS NULL)",
            name="ck_messages_kind_body_xor",
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_messages_chat_client_msg_id ON messages (chat_id, client_msg_id) "
        "WHERE client_msg_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_messages_chat_created ON messages (chat_id, created_at DESC, id DESC)"
    )


def downgrade() -> None:
    op.drop_index("ix_messages_chat_created", table_name="messages")
    op.drop_index("uq_messages_chat_client_msg_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_files_chat_id", table_name="files")
    op.drop_table("files")
    op.drop_index("ix_chats_last_message_at", table_name="chats")
    op.drop_index("ix_chats_owner_user_id", table_name="chats")
    op.drop_table("chats")
    op.drop_index("ix_support_agents_login", table_name="support_agents")
    op.drop_table("support_agents")
```

- [ ] **Step 3: Apply the migration against a dev DB**

Bring up Postgres (assumes `docker-compose` defines a `database` service):
```bash
docker compose up -d database
```

Wait a moment, then:
```bash
uv run alembic upgrade head
```
Expected: `INFO  [alembic.runtime.migration] Running upgrade  -> 20260521_0001, chat domain`.

- [ ] **Step 4: Inspect schema**

Run:
```bash
docker compose exec database psql -U postgres -d insurance_platform -c "\dt" | grep -E "chats|messages|files|support_agents"
```
Expected: all 4 tables listed.

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/
git commit -m "migration: chat domain (4 tables)"
```

---

## Phase 3 — Test infrastructure

### Task 3.1: Expand `conftest.py` with DB + client fixtures

**Files:** Modify `tests/conftest.py`

- [ ] **Step 1: Replace `tests/conftest.py`**

```python
"""Test fixtures.

Strategy:
- Session-scoped async engine bound to a separate test database.
- Per-test outer transaction with rollback (no schema teardown between tests).
- TestClient via httpx.AsyncClient + ASGITransport (in-process).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import AsyncIterator

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Force the test database name BEFORE importing app.* (config reads env at import).
os.environ.setdefault("DB_NAME", "insurance_platform_test")

from app.core.config import settings  # noqa: E402
from app.core.database import get_async_session  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def engine():
    engine = create_async_engine(settings.database_url, echo=False, future=True)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(engine) -> AsyncIterator[AsyncSession]:
    """Per-test session inside a transaction that always rolls back."""
    connection = await engine.connect()
    transaction = await connection.begin()
    session_maker = async_sessionmaker(bind=connection, expire_on_commit=False, class_=AsyncSession)
    session = session_maker()
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest.fixture
async def client(db_session) -> AsyncIterator[httpx.AsyncClient]:
    """FastAPI test client. Overrides get_async_session to use the test transaction."""

    async def _override():
        yield db_session

    app.dependency_overrides[get_async_session] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def make_user_id():
    """Counter so each test gets a unique synthetic users.id without inserting a real user."""
    seq = {"n": 1_000_000}

    def _next() -> int:
        seq["n"] += 1
        return seq["n"]

    return _next


@pytest.fixture
def make_chat_id():
    def _make() -> uuid.UUID:
        return uuid.uuid4()
    return _make
```

- [ ] **Step 2: Verify the smoke test still passes**

Run: `uv run pytest tests/unit/test_smoke.py -v`
Expected: 1 passed.

- [ ] **Step 3: Create the test DB and apply migrations to it**

Run:
```bash
docker compose exec database psql -U postgres -c "CREATE DATABASE insurance_platform_test"
DB_NAME=insurance_platform_test uv run alembic upgrade head
```
Expected: migration runs cleanly on the test DB.

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py
git commit -m "tests: db + httpx async client fixtures"
```

---

## Phase 4 — Auth dependencies

### Task 4.1: `internal_secret_required` dependency

**Files:**
- Create: `app/api/deps/__init__.py`
- Create: `app/api/deps/internal_secret.py`

- [ ] **Step 1: Create empty `__init__.py`**

```bash
touch app/api/deps/__init__.py
```

- [ ] **Step 2: Write failing test**

Create `tests/unit/test_internal_secret.py`:

```python
import pytest
from fastapi import HTTPException

from app.api.deps.internal_secret import internal_secret_required


@pytest.mark.asyncio
async def test_accepts_matching_secret(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "internal_secret", "the-real-secret")

    # Should not raise.
    await internal_secret_required(x_internal_secret="the-real-secret")


@pytest.mark.asyncio
async def test_rejects_wrong_secret(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "internal_secret", "the-real-secret")

    with pytest.raises(HTTPException) as ei:
        await internal_secret_required(x_internal_secret="wrong")
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_rejects_missing_header(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "internal_secret", "the-real-secret")

    with pytest.raises(HTTPException) as ei:
        await internal_secret_required(x_internal_secret="")
    assert ei.value.status_code == 403
```

- [ ] **Step 3: Run (fails)**

Run: `uv run pytest tests/unit/test_internal_secret.py -v`
Expected: ImportError.

- [ ] **Step 4: Write `app/api/deps/internal_secret.py`**

```python
import secrets

from fastapi import Header, HTTPException, status

from app.core.config import settings


async def internal_secret_required(
    x_internal_secret: str = Header(default="", alias="X-Internal-Secret"),
) -> None:
    expected = settings.internal_secret
    if not expected:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal secret not configured")
    if not secrets.compare_digest(x_internal_secret, expected):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
```

- [ ] **Step 5: Run tests (pass)**

Run: `uv run pytest tests/unit/test_internal_secret.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add app/api/deps/ tests/unit/test_internal_secret.py
git commit -m "deps: internal_secret_required"
```

### Task 4.2: `admin_basic_auth` dependency

**Files:**
- Create: `app/api/deps/admin_auth.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_admin_auth.py`:

```python
import base64

import pytest
from fastapi import HTTPException

from app.api.deps.admin_auth import admin_basic_auth


def _basic(login: str, password: str) -> str:
    raw = f"{login}:{password}".encode()
    return "Basic " + base64.b64encode(raw).decode()


@pytest.mark.asyncio
async def test_accepts_correct_credentials(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_login", "admin")
    monkeypatch.setattr(settings, "admin_password", "s3cret")

    await admin_basic_auth(authorization=_basic("admin", "s3cret"))


@pytest.mark.asyncio
async def test_rejects_wrong_password(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_login", "admin")
    monkeypatch.setattr(settings, "admin_password", "s3cret")

    with pytest.raises(HTTPException) as ei:
        await admin_basic_auth(authorization=_basic("admin", "wrong"))
    assert ei.value.status_code == 401


@pytest.mark.asyncio
async def test_rejects_missing_header(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_login", "admin")
    monkeypatch.setattr(settings, "admin_password", "s3cret")

    with pytest.raises(HTTPException) as ei:
        await admin_basic_auth(authorization="")
    assert ei.value.status_code == 401


@pytest.mark.asyncio
async def test_rejects_non_basic_scheme(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_login", "admin")
    monkeypatch.setattr(settings, "admin_password", "s3cret")

    with pytest.raises(HTTPException) as ei:
        await admin_basic_auth(authorization="Bearer foo")
    assert ei.value.status_code == 401
```

- [ ] **Step 2: Run (fails)**

Run: `uv run pytest tests/unit/test_admin_auth.py -v`
Expected: ImportError.

- [ ] **Step 3: Write `app/api/deps/admin_auth.py`**

```python
import base64
import secrets

from fastapi import Header, HTTPException, status

from app.core.config import settings


async def admin_basic_auth(authorization: str = Header(default="")) -> None:
    if not authorization.lower().startswith("basic "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="basic auth required",
            headers={"WWW-Authenticate": 'Basic realm="admin"'},
        )
    try:
        decoded = base64.b64decode(authorization.split(" ", 1)[1]).decode("utf-8")
        login, password = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="malformed credentials")

    login_ok = secrets.compare_digest(login, settings.admin_login)
    password_ok = secrets.compare_digest(password, settings.admin_password)
    if not (login_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
            headers={"WWW-Authenticate": 'Basic realm="admin"'},
        )
```

- [ ] **Step 4: Run (passes)**

Run: `uv run pytest tests/unit/test_admin_auth.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/api/deps/admin_auth.py tests/unit/test_admin_auth.py
git commit -m "deps: admin_basic_auth"
```

### Task 4.3: Subject parsing helper + `get_current_subject` + `get_current_support`

**Files:**
- Create: `app/api/deps/subject_auth.py`
- Create: `app/api/deps/support_auth.py`

- [ ] **Step 1: Write failing test for subject parsing**

Create `tests/unit/test_subject_parsing.py`:

```python
import pytest

from app.api.deps.subject_auth import Subject, parse_subject_claim


def test_parses_user_subject():
    assert parse_subject_claim("user:42") == Subject(type="user", id=42)


def test_parses_support_subject():
    assert parse_subject_claim("support:7") == Subject(type="support", id=7)


@pytest.mark.parametrize("bad", ["", "user:", ":42", "user:abc", "admin:1", "user:42:extra"])
def test_rejects_malformed(bad):
    with pytest.raises(ValueError):
        parse_subject_claim(bad)
```

- [ ] **Step 2: Run (fails)**

Run: `uv run pytest tests/unit/test_subject_parsing.py -v`
Expected: ImportError.

- [ ] **Step 3: Write `app/api/deps/subject_auth.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_async_session
from app.models.tables.support_agent import SupportAgent
from app.models.users.entities import User


SubjectType = Literal["user", "support"]


@dataclass(frozen=True)
class Subject:
    type: SubjectType
    id: int


@dataclass(frozen=True)
class SubjectRow:
    """Resolved subject — type/id plus the row from the matching table."""
    subject: Subject
    user: User | None = None
    support: SupportAgent | None = None


def parse_subject_claim(value: str) -> Subject:
    """Parse `"user:42"` / `"support:7"`. Raises ValueError on anything else."""
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError(f"malformed sub claim: {value!r}")
    kind, raw_id = parts
    if kind not in ("user", "support"):
        raise ValueError(f"unknown subject kind: {kind!r}")
    if not raw_id:
        raise ValueError("subject id missing")
    try:
        sid = int(raw_id)
    except ValueError as e:
        raise ValueError(f"subject id not an integer: {raw_id!r}") from e
    return Subject(type=kind, id=sid)


_bearer = HTTPBearer(auto_error=False)


def _credentials_exception(detail: str = "Could not validate credentials") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_subject(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_async_session),
) -> SubjectRow:
    if credentials is None:
        raise _credentials_exception("missing bearer token")
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as e:
        raise _credentials_exception(str(e))
    sub_claim = payload.get("sub")
    if not isinstance(sub_claim, str):
        raise _credentials_exception("missing sub claim")
    try:
        subject = parse_subject_claim(sub_claim)
    except ValueError as e:
        raise _credentials_exception(str(e))

    if subject.type == "user":
        row = await session.execute(select(User).where(User.id == subject.id))
        user = row.scalar_one_or_none()
        if user is None:
            raise _credentials_exception("user not found")
        return SubjectRow(subject=subject, user=user)
    else:
        row = await session.execute(select(SupportAgent).where(SupportAgent.id == subject.id))
        support = row.scalar_one_or_none()
        if support is None or not support.is_active:
            raise _credentials_exception("support agent not found or inactive")
        return SubjectRow(subject=subject, support=support)
```

- [ ] **Step 4: Write `app/api/deps/support_auth.py`**

```python
from fastapi import Depends, HTTPException, status

from app.api.deps.subject_auth import SubjectRow, get_current_subject


async def get_current_support(subject: SubjectRow = Depends(get_current_subject)) -> SubjectRow:
    if subject.subject.type != "support" or subject.support is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="support role required")
    return subject
```

- [ ] **Step 5: Run unit tests**

Run: `uv run pytest tests/unit/test_subject_parsing.py -v`
Expected: 5+ passed (`parse_subject_claim` parametrize counts as multiple).

- [ ] **Step 6: Commit**

```bash
git add app/api/deps/subject_auth.py app/api/deps/support_auth.py tests/unit/test_subject_parsing.py
git commit -m "deps: subject + support auth"
```

---

## Phase 5 — User JWT additive change

### Task 5.1: Add `sub` and `role` claims to user JWT

**Files:** Modify `app/services/auth_service.py`

- [ ] **Step 1: Write failing test**

Create `tests/integration/test_user_jwt_claims.py`:

```python
import pytest
from jose import jwt
from sqlalchemy import select

from app.core.config import settings
from app.models.users.entities import User
from app.services.auth_service import AuthService


@pytest.mark.asyncio
async def test_user_access_token_carries_sub_and_role(db_session):
    svc = AuthService(db_session)
    token = svc._generate_access_token(user_id=1234)
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    assert payload["user_id"] == 1234
    assert payload["sub"] == "user:1234"
    assert payload["role"] == "user"
    assert payload["type"] == "access"
```

- [ ] **Step 2: Run (fails)**

Run: `uv run pytest tests/integration/test_user_jwt_claims.py -v`
Expected: FAIL with `KeyError: 'sub'`.

- [ ] **Step 3: Edit `_generate_access_token`**

In `app/services/auth_service.py`, change the function to:

```python
    def _generate_access_token(self, user_id: int) -> str:
        payload = {
            "user_id": user_id,
            "sub": f"user:{user_id}",
            "role": "user",
            "type": "access",
            "exp": datetime.utcnow() + timedelta(minutes=settings.jwt_access_token_expire_minutes),
            "iat": datetime.utcnow(),
        }
        return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
```

- [ ] **Step 4: Run (passes)**

Run: `uv run pytest tests/integration/test_user_jwt_claims.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/auth_service.py tests/integration/test_user_jwt_claims.py
git commit -m "auth: add sub and role claims to user JWT"
```

---

## Phase 6 — Support agent flow

### Task 6.1: Support auth service + DTOs

**Files:**
- Create: `app/models/dto/support_agent.py`
- Create: `app/services/support_auth_service.py`

- [ ] **Step 1: Write DTOs**

Create `app/models/dto/support_agent.py`:

```python
from datetime import datetime

from pydantic import BaseModel, Field


class SupportLoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class SupportTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class SupportAgentCreate(BaseModel):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(min_length=1, max_length=100)


class SupportAgentUpdate(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=200)
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None


class SupportAgentResponse(BaseModel):
    id: int
    login: str
    display_name: str
    is_active: bool
    created_at: datetime
```

- [ ] **Step 2: Write failing test for support login service**

Create `tests/integration/test_support_login.py`:

```python
import pytest

from app.models.tables.support_agent import SupportAgent
from app.services.support_auth_service import SupportAuthService
from passlib.context import CryptContext

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


@pytest.mark.asyncio
async def test_login_returns_token_for_active_agent(db_session):
    agent = SupportAgent(login="alice", password_hash=pwd.hash("p4ssw0rd"), display_name="Alice", is_active=True)
    db_session.add(agent)
    await db_session.commit()

    svc = SupportAuthService(db_session)
    result = await svc.login("alice", "p4ssw0rd")
    assert result.access_token
    assert result.token_type == "bearer"
    assert result.expires_in > 0


@pytest.mark.asyncio
async def test_login_rejects_inactive_agent(db_session):
    agent = SupportAgent(login="bob", password_hash=pwd.hash("p4ssw0rd"), display_name="Bob", is_active=False)
    db_session.add(agent)
    await db_session.commit()

    svc = SupportAuthService(db_session)
    with pytest.raises(ValueError):
        await svc.login("bob", "p4ssw0rd")


@pytest.mark.asyncio
async def test_login_rejects_wrong_password(db_session):
    agent = SupportAgent(login="carol", password_hash=pwd.hash("right"), display_name="Carol", is_active=True)
    db_session.add(agent)
    await db_session.commit()

    svc = SupportAuthService(db_session)
    with pytest.raises(ValueError):
        await svc.login("carol", "wrong")
```

- [ ] **Step 3: Run (fails)**

Run: `uv run pytest tests/integration/test_support_login.py -v`
Expected: ImportError.

- [ ] **Step 4: Write `app/services/support_auth_service.py`**

```python
from datetime import datetime, timedelta

from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.dto.support_agent import SupportTokenResponse
from app.models.tables.support_agent import SupportAgent


_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


class SupportAuthService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def login(self, login: str, password: str) -> SupportTokenResponse:
        row = await self._session.execute(select(SupportAgent).where(SupportAgent.login == login))
        agent = row.scalar_one_or_none()
        if agent is None or not agent.is_active:
            raise ValueError("invalid credentials")
        if not _pwd.verify(password, agent.password_hash):
            raise ValueError("invalid credentials")

        expires = settings.jwt_access_token_expire_minutes * 60
        now = datetime.utcnow()
        payload = {
            "sub": f"support:{agent.id}",
            "role": "support",
            "subject_type": "support",
            "subject_id": agent.id,
            "type": "access",
            "exp": now + timedelta(seconds=expires),
            "iat": now,
        }
        token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
        return SupportTokenResponse(access_token=token, token_type="bearer", expires_in=expires)
```

- [ ] **Step 5: Run (passes)**

Run: `uv run pytest tests/integration/test_support_login.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add app/models/dto/support_agent.py app/services/support_auth_service.py tests/integration/test_support_login.py
git commit -m "support: auth service + DTOs"
```

### Task 6.2: Support repository

**Files:**
- Create: `app/repositories/support_agent_repository.py`

- [ ] **Step 1: Write failing test**

Create `tests/integration/test_support_agent_repository.py`:

```python
import pytest

from app.repositories.support_agent_repository import SupportAgentRepository


@pytest.mark.asyncio
async def test_create_and_get(db_session):
    repo = SupportAgentRepository(db_session)
    agent = await repo.create(login="dave", password_hash="x", display_name="Dave")
    assert agent.id is not None
    got = await repo.get_by_id(agent.id)
    assert got is not None and got.login == "dave"


@pytest.mark.asyncio
async def test_get_by_login(db_session):
    repo = SupportAgentRepository(db_session)
    await repo.create(login="eve", password_hash="x", display_name="Eve")
    got = await repo.get_by_login("eve")
    assert got is not None and got.login == "eve"


@pytest.mark.asyncio
async def test_list_active_only(db_session):
    repo = SupportAgentRepository(db_session)
    await repo.create(login="active", password_hash="x", display_name="Active")
    inactive = await repo.create(login="inactive", password_hash="x", display_name="Inactive")
    inactive.is_active = False
    await db_session.commit()

    active_list = await repo.list(active_only=True, limit=50, offset=0)
    assert {a.login for a in active_list} >= {"active"}
    assert "inactive" not in {a.login for a in active_list}

    full_list = await repo.list(active_only=False, limit=50, offset=0)
    logins = {a.login for a in full_list}
    assert {"active", "inactive"} <= logins
```

- [ ] **Step 2: Run (fails)**

Run: `uv run pytest tests/integration/test_support_agent_repository.py -v`
Expected: ImportError.

- [ ] **Step 3: Write `app/repositories/support_agent_repository.py`**

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables.support_agent import SupportAgent


class SupportAgentRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, *, login: str, password_hash: str, display_name: str) -> SupportAgent:
        agent = SupportAgent(login=login, password_hash=password_hash, display_name=display_name, is_active=True)
        self._session.add(agent)
        await self._session.flush()
        await self._session.refresh(agent)
        return agent

    async def get_by_id(self, agent_id: int) -> SupportAgent | None:
        row = await self._session.execute(select(SupportAgent).where(SupportAgent.id == agent_id))
        return row.scalar_one_or_none()

    async def get_by_login(self, login: str) -> SupportAgent | None:
        row = await self._session.execute(select(SupportAgent).where(SupportAgent.login == login))
        return row.scalar_one_or_none()

    async def list(self, *, active_only: bool, limit: int, offset: int) -> list[SupportAgent]:
        stmt = select(SupportAgent).order_by(SupportAgent.id).limit(limit).offset(offset)
        if active_only:
            stmt = stmt.where(SupportAgent.is_active.is_(True))
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())
```

- [ ] **Step 4: Run (passes)**

Run: `uv run pytest tests/integration/test_support_agent_repository.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/repositories/support_agent_repository.py tests/integration/test_support_agent_repository.py
git commit -m "repo: support_agent_repository"
```

### Task 6.3: Admin router (CRUD for support agents)

**Files:**
- Create: `app/api/routers/admin.py`

- [ ] **Step 1: Write failing test**

Create `tests/integration/test_admin_support_agents.py`:

```python
import base64

import pytest

from app.core.config import settings


def _basic(monkeypatch) -> dict[str, str]:
    monkeypatch.setattr(settings, "admin_login", "admin")
    monkeypatch.setattr(settings, "admin_password", "secret")
    creds = base64.b64encode(b"admin:secret").decode()
    return {"Authorization": f"Basic {creds}"}


@pytest.mark.asyncio
async def test_create_list_update_delete_flow(client, monkeypatch):
    headers = _basic(monkeypatch)

    # Create
    r = await client.post(
        "/api/v1/admin/support-agents/",
        json={"login": "alice", "password": "p4ssw0rd1", "display_name": "Alice"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["login"] == "alice"
    assert created["is_active"] is True
    aid = created["id"]

    # Duplicate login → 409
    r2 = await client.post(
        "/api/v1/admin/support-agents/",
        json={"login": "alice", "password": "p4ssw0rd2", "display_name": "Alice 2"},
        headers=headers,
    )
    assert r2.status_code == 409

    # List
    r3 = await client.get("/api/v1/admin/support-agents/", headers=headers)
    assert r3.status_code == 200
    logins = {a["login"] for a in r3.json()["agents"]}
    assert "alice" in logins

    # Patch (soft-disable)
    r4 = await client.patch(
        f"/api/v1/admin/support-agents/{aid}/", json={"is_active": False}, headers=headers,
    )
    assert r4.status_code == 200
    assert r4.json()["is_active"] is False

    # active_only filter
    r5 = await client.get("/api/v1/admin/support-agents/?active_only=true", headers=headers)
    assert "alice" not in {a["login"] for a in r5.json()["agents"]}

    # Delete (soft delete)
    r6 = await client.delete(f"/api/v1/admin/support-agents/{aid}/", headers=headers)
    assert r6.status_code == 204


@pytest.mark.asyncio
async def test_admin_endpoint_rejects_no_auth(client):
    r = await client.get("/api/v1/admin/support-agents/")
    assert r.status_code == 401
```

- [ ] **Step 2: Run (fails)**

Run: `uv run pytest tests/integration/test_admin_support_agents.py -v`
Expected: 404 / ImportError.

- [ ] **Step 3: Write `app/api/routers/admin.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, Query, status
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.admin_auth import admin_basic_auth
from app.core.database import get_async_session
from app.models.dto.support_agent import (
    SupportAgentCreate,
    SupportAgentResponse,
    SupportAgentUpdate,
)
from app.repositories.support_agent_repository import SupportAgentRepository


_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(admin_basic_auth)])


class SupportAgentList(BaseModel):
    agents: list[SupportAgentResponse]


@router.post("/support-agents/", response_model=SupportAgentResponse, status_code=status.HTTP_201_CREATED)
async def create_support_agent(
    payload: SupportAgentCreate,
    session: AsyncSession = Depends(get_async_session),
) -> SupportAgentResponse:
    repo = SupportAgentRepository(session)
    if await repo.get_by_login(payload.login) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="login already exists")
    try:
        agent = await repo.create(
            login=payload.login,
            password_hash=_pwd.hash(payload.password),
            display_name=payload.display_name,
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="login already exists")
    return SupportAgentResponse.model_validate(agent, from_attributes=True)


@router.get("/support-agents/", response_model=SupportAgentList)
async def list_support_agents(
    active_only: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_async_session),
) -> SupportAgentList:
    repo = SupportAgentRepository(session)
    rows = await repo.list(active_only=active_only, limit=limit, offset=offset)
    return SupportAgentList(agents=[SupportAgentResponse.model_validate(a, from_attributes=True) for a in rows])


@router.patch("/support-agents/{agent_id}/", response_model=SupportAgentResponse)
async def patch_support_agent(
    agent_id: int,
    payload: SupportAgentUpdate,
    session: AsyncSession = Depends(get_async_session),
) -> SupportAgentResponse:
    repo = SupportAgentRepository(session)
    agent = await repo.get_by_id(agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    if payload.password is not None:
        agent.password_hash = _pwd.hash(payload.password)
    if payload.display_name is not None:
        agent.display_name = payload.display_name
    if payload.is_active is not None:
        agent.is_active = payload.is_active
    await session.commit()
    await session.refresh(agent)
    return SupportAgentResponse.model_validate(agent, from_attributes=True)


@router.delete("/support-agents/{agent_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_support_agent(
    agent_id: int,
    session: AsyncSession = Depends(get_async_session),
) -> None:
    repo = SupportAgentRepository(session)
    agent = await repo.get_by_id(agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    agent.is_active = False
    await session.commit()
```

- [ ] **Step 4: Wire the router into the main router**

Edit `app/api/main_router.py`. Add at the import block:
```python
from app.api.routers.admin import router as admin_router
```
And add at the bottom:
```python
api_router.include_router(admin_router)
```

- [ ] **Step 5: Run (passes)**

Run: `uv run pytest tests/integration/test_admin_support_agents.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add app/api/routers/admin.py app/api/main_router.py tests/integration/test_admin_support_agents.py
git commit -m "admin: support-agents CRUD"
```

### Task 6.4: Support login + support-chats router

**Files:**
- Create: `app/api/routers/support.py`

(Support-chats listing requires `chat_repository`; that's Phase 7. Skip the listing endpoint here and add the login endpoint only. Listing comes in Task 7.4.)

- [ ] **Step 1: Write failing test**

Create `tests/integration/test_support_login_endpoint.py`:

```python
import pytest
from passlib.context import CryptContext

from app.models.tables.support_agent import SupportAgent

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


@pytest.mark.asyncio
async def test_support_login_returns_token(client, db_session):
    db_session.add(SupportAgent(login="frank", password_hash=pwd.hash("openme"), display_name="Frank", is_active=True))
    await db_session.commit()

    r = await client.post("/api/v1/support/login/", json={"login": "frank", "password": "openme"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["expires_in"] > 0


@pytest.mark.asyncio
async def test_support_login_bad_creds(client, db_session):
    db_session.add(SupportAgent(login="grace", password_hash=pwd.hash("right"), display_name="Grace", is_active=True))
    await db_session.commit()

    r = await client.post("/api/v1/support/login/", json={"login": "grace", "password": "wrong"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_support_login_inactive(client, db_session):
    db_session.add(SupportAgent(login="hank", password_hash=pwd.hash("openme"), display_name="Hank", is_active=False))
    await db_session.commit()

    r = await client.post("/api/v1/support/login/", json={"login": "hank", "password": "openme"})
    assert r.status_code == 401
```

- [ ] **Step 2: Run (fails)**

Run: `uv run pytest tests/integration/test_support_login_endpoint.py -v`
Expected: 404.

- [ ] **Step 3: Write `app/api/routers/support.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.models.dto.support_agent import SupportLoginRequest, SupportTokenResponse
from app.services.support_auth_service import SupportAuthService


router = APIRouter(prefix="/support", tags=["support"])


@router.post("/login/", response_model=SupportTokenResponse)
async def support_login(
    payload: SupportLoginRequest,
    session: AsyncSession = Depends(get_async_session),
) -> SupportTokenResponse:
    svc = SupportAuthService(session)
    try:
        return await svc.login(payload.login, payload.password)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
```

- [ ] **Step 4: Wire router into `main_router.py`**

Add import:
```python
from app.api.routers.support import router as support_router
```
Add include:
```python
api_router.include_router(support_router)
```

- [ ] **Step 5: Run (passes)**

Run: `uv run pytest tests/integration/test_support_login_endpoint.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add app/api/routers/support.py app/api/main_router.py tests/integration/test_support_login_endpoint.py
git commit -m "support: login endpoint"
```

---

## Phase 7 — Chat & message domain

### Task 7.1: Chat repository

**Files:**
- Create: `app/repositories/chat_repository.py`

- [ ] **Step 1: Write failing test**

Create `tests/integration/test_chat_repository.py`:

```python
import pytest

from app.repositories.chat_repository import ChatRepository


@pytest.fixture
async def real_user(db_session):
    """Insert a real user row so chat FK is satisfied."""
    from app.models.users.entities import User
    user = User(
        email="x@y.z", phone="+1000000001", password_hash="x",
        first_name="X", last_name="Y", patronymic=None,
        referral_code="REF001", referrer_id=None,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_get_or_create_lazy_creates_main(db_session, real_user):
    repo = ChatRepository(db_session)
    chat = await repo.get_or_create_for_user(owner_user_id=real_user.id, chat_type="main")
    assert chat.owner_user_id == real_user.id
    assert chat.type == "main"
    assert chat.id is not None


@pytest.mark.asyncio
async def test_get_or_create_is_idempotent(db_session, real_user):
    repo = ChatRepository(db_session)
    a = await repo.get_or_create_for_user(owner_user_id=real_user.id, chat_type="main")
    b = await repo.get_or_create_for_user(owner_user_id=real_user.id, chat_type="main")
    assert a.id == b.id


@pytest.mark.asyncio
async def test_get_by_id(db_session, real_user):
    repo = ChatRepository(db_session)
    created = await repo.get_or_create_for_user(owner_user_id=real_user.id, chat_type="bonus")
    found = await repo.get_by_id(created.id)
    assert found is not None and found.id == created.id


@pytest.mark.asyncio
async def test_list_for_user(db_session, real_user):
    repo = ChatRepository(db_session)
    await repo.get_or_create_for_user(owner_user_id=real_user.id, chat_type="main")
    await repo.get_or_create_for_user(owner_user_id=real_user.id, chat_type="bonus")
    rows = await repo.list_for_user(real_user.id)
    types = {c.type for c in rows}
    assert types == {"main", "bonus"}


@pytest.mark.asyncio
async def test_list_active_for_support(db_session, real_user):
    repo = ChatRepository(db_session)
    main = await repo.get_or_create_for_user(owner_user_id=real_user.id, chat_type="main")
    # Simulate activity by bumping last_message_at
    from datetime import datetime, timezone
    main.last_message_at = datetime.now(timezone.utc)
    await db_session.commit()

    rows = await repo.list_active_for_support(chat_type=None, limit=50, before=None, include_empty=False)
    assert any(c.id == main.id for c in rows)
```

- [ ] **Step 2: Run (fails)**

Run: `uv run pytest tests/integration/test_chat_repository.py -v`
Expected: ImportError.

- [ ] **Step 3: Write `app/repositories/chat_repository.py`**

```python
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables.chat import Chat


class ChatRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_or_create_for_user(self, *, owner_user_id: int, chat_type: str) -> Chat:
        """Idempotent under the UNIQUE(owner_user_id, type) constraint."""
        stmt = (
            pg_insert(Chat)
            .values(owner_user_id=owner_user_id, type=chat_type)
            .on_conflict_do_nothing(index_elements=["owner_user_id", "type"])
            .returning(Chat.id)
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        inserted_id = result.scalar_one_or_none()
        if inserted_id is None:
            existing = await self._session.execute(
                select(Chat).where(Chat.owner_user_id == owner_user_id, Chat.type == chat_type)
            )
            chat = existing.scalar_one()
        else:
            existing = await self._session.execute(select(Chat).where(Chat.id == inserted_id))
            chat = existing.scalar_one()
        return chat

    async def get_by_id(self, chat_id: UUID) -> Chat | None:
        row = await self._session.execute(select(Chat).where(Chat.id == chat_id))
        return row.scalar_one_or_none()

    async def list_for_user(self, owner_user_id: int) -> list[Chat]:
        rows = await self._session.execute(
            select(Chat).where(Chat.owner_user_id == owner_user_id).order_by(Chat.type)
        )
        return list(rows.scalars().all())

    async def list_active_for_support(
        self,
        *,
        chat_type: str | None,
        limit: int,
        before: datetime | None,
        include_empty: bool,
    ) -> list[Chat]:
        stmt = select(Chat).order_by(Chat.last_message_at.desc().nullslast(), Chat.id).limit(limit)
        if chat_type is not None:
            stmt = stmt.where(Chat.type == chat_type)
        if not include_empty:
            stmt = stmt.where(Chat.last_message_at.is_not(None))
        if before is not None:
            stmt = stmt.where(Chat.last_message_at < before)
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())

    async def bump_last_message_at(self, chat_id: UUID) -> None:
        await self._session.execute(
            Chat.__table__.update().where(Chat.id == chat_id).values(last_message_at=func.now())
        )
```

- [ ] **Step 4: Run (passes)**

Run: `uv run pytest tests/integration/test_chat_repository.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add app/repositories/chat_repository.py tests/integration/test_chat_repository.py
git commit -m "repo: chat_repository"
```

### Task 7.2: Message repository

**Files:**
- Create: `app/repositories/message_repository.py`

- [ ] **Step 1: Write failing test**

Create `tests/integration/test_message_repository.py`:

```python
import pytest

from app.repositories.chat_repository import ChatRepository
from app.repositories.message_repository import MessageRepository


@pytest.fixture
async def chat(db_session):
    from app.models.users.entities import User
    u = User(email="x@y.z", phone="+1000000002", password_hash="x", first_name=None, last_name=None,
            patronymic=None, referral_code="REF002", referrer_id=None)
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)

    repo = ChatRepository(db_session)
    return await repo.get_or_create_for_user(owner_user_id=u.id, chat_type="main")


@pytest.mark.asyncio
async def test_insert_and_get_existing(db_session, chat):
    repo = MessageRepository(db_session)
    msg, created = await repo.insert_or_get(
        chat_id=chat.id,
        sender_subject_type="user",
        sender_subject_id=42,
        kind="message",
        body="hello",
        file_id=None,
        client_msg_id="cli-1",
    )
    assert created is True

    msg2, created2 = await repo.insert_or_get(
        chat_id=chat.id,
        sender_subject_type="user",
        sender_subject_id=42,
        kind="message",
        body="hello",
        file_id=None,
        client_msg_id="cli-1",
    )
    assert created2 is False
    assert msg2.id == msg.id


@pytest.mark.asyncio
async def test_list_history_paginates(db_session, chat):
    repo = MessageRepository(db_session)
    ids = []
    for i in range(5):
        m, _ = await repo.insert_or_get(
            chat_id=chat.id, sender_subject_type="user", sender_subject_id=42,
            kind="message", body=f"m{i}", file_id=None, client_msg_id=f"c{i}",
        )
        ids.append(m.id)

    first_page = await repo.list_history(chat_id=chat.id, limit=3, before_id=None)
    assert len(first_page) == 3
    next_page = await repo.list_history(chat_id=chat.id, limit=3, before_id=first_page[-1].id)
    assert len(next_page) == 2
```

- [ ] **Step 2: Run (fails)**

Run: `uv run pytest tests/integration/test_message_repository.py -v`
Expected: ImportError.

- [ ] **Step 3: Write `app/repositories/message_repository.py`**

```python
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables.message import Message


class MessageRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def insert_or_get(
        self,
        *,
        chat_id: UUID,
        sender_subject_type: str,
        sender_subject_id: int,
        kind: str,
        body: str | None,
        file_id: UUID | None,
        client_msg_id: str | None,
    ) -> tuple[Message, bool]:
        """Returns (row, created). Idempotent on (chat_id, client_msg_id)."""
        if client_msg_id is not None:
            existing = await self._session.execute(
                select(Message).where(Message.chat_id == chat_id, Message.client_msg_id == client_msg_id)
            )
            existing_row = existing.scalar_one_or_none()
            if existing_row is not None:
                return existing_row, False

        msg = Message(
            chat_id=chat_id,
            sender_subject_type=sender_subject_type,
            sender_subject_id=sender_subject_id,
            kind=kind,
            body=body,
            file_id=file_id,
            client_msg_id=client_msg_id,
        )
        self._session.add(msg)
        try:
            await self._session.flush()
        except Exception:
            await self._session.rollback()
            # Concurrent insert raced us — re-read.
            row = await self._session.execute(
                select(Message).where(Message.chat_id == chat_id, Message.client_msg_id == client_msg_id)
            )
            existing_row = row.scalar_one()
            return existing_row, False

        await self._session.refresh(msg)
        return msg, True

    async def list_history(
        self,
        *,
        chat_id: UUID,
        limit: int,
        before_id: UUID | None,
    ) -> list[Message]:
        """Returns up to `limit` rows ordered newest-first. If `before_id` is set,
        returns rows older than that message (cursor pagination)."""
        stmt = select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at.desc(), Message.id.desc()).limit(limit)
        if before_id is not None:
            cursor = await self._session.execute(select(Message).where(Message.id == before_id))
            cursor_row = cursor.scalar_one_or_none()
            if cursor_row is None:
                return []
            stmt = stmt.where(
                (Message.created_at < cursor_row.created_at)
                | ((Message.created_at == cursor_row.created_at) & (Message.id < cursor_row.id))
            )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())
```

- [ ] **Step 4: Run (passes)**

Run: `uv run pytest tests/integration/test_message_repository.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add app/repositories/message_repository.py tests/integration/test_message_repository.py
git commit -m "repo: message_repository (idempotent insert + cursor list)"
```

### Task 7.3: File repository

**Files:**
- Create: `app/repositories/file_repository.py`

- [ ] **Step 1: Write failing test**

Create `tests/integration/test_file_repository.py`:

```python
import pytest

from app.repositories.chat_repository import ChatRepository
from app.repositories.file_repository import FileRepository


@pytest.fixture
async def chat(db_session):
    from app.models.users.entities import User
    u = User(email="x@y.z", phone="+1000000003", password_hash="x",
            first_name=None, last_name=None, patronymic=None,
            referral_code="REF003", referrer_id=None)
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    repo = ChatRepository(db_session)
    return await repo.get_or_create_for_user(owner_user_id=u.id, chat_type="main")


@pytest.mark.asyncio
async def test_create_and_get(db_session, chat):
    repo = FileRepository(db_session)
    f = await repo.create(
        chat_id=chat.id, uploader_subject_type="user", uploader_subject_id=42,
        original_name="report.pdf", mime_type="application/pdf", size_bytes=12345,
        minio_key=f"chats/{chat.id}/test",
    )
    await db_session.commit()
    got = await repo.get_by_id(f.id)
    assert got is not None and got.original_name == "report.pdf"
```

- [ ] **Step 2: Run (fails)**

Run: `uv run pytest tests/integration/test_file_repository.py -v`
Expected: ImportError.

- [ ] **Step 3: Write `app/repositories/file_repository.py`**

```python
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables.file import File


class FileRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        *,
        chat_id: UUID,
        uploader_subject_type: str,
        uploader_subject_id: int,
        original_name: str,
        mime_type: str,
        size_bytes: int,
        minio_key: str,
    ) -> File:
        f = File(
            chat_id=chat_id,
            uploader_subject_type=uploader_subject_type,
            uploader_subject_id=uploader_subject_id,
            original_name=original_name,
            mime_type=mime_type,
            size_bytes=size_bytes,
            minio_key=minio_key,
        )
        self._session.add(f)
        await self._session.flush()
        await self._session.refresh(f)
        return f

    async def get_by_id(self, file_id: UUID) -> File | None:
        row = await self._session.execute(select(File).where(File.id == file_id))
        return row.scalar_one_or_none()
```

- [ ] **Step 4: Run (passes)**

Run: `uv run pytest tests/integration/test_file_repository.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add app/repositories/file_repository.py tests/integration/test_file_repository.py
git commit -m "repo: file_repository"
```

### Task 7.4: Support-chats listing endpoint

**Files:** Modify `app/api/routers/support.py`

- [ ] **Step 1: Write DTOs in `app/models/dto/chat.py`**

Create `app/models/dto/chat.py`:

```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ChatResponse(BaseModel):
    id: UUID
    type: str
    last_message_at: datetime | None


class ChatList(BaseModel):
    chats: list[ChatResponse]


class ChatCreate(BaseModel):
    type: str  # "main" | "bonus" — validated in the handler


class SupportChatItem(BaseModel):
    id: UUID
    type: str
    owner: "OwnerInfo"
    last_message_at: datetime | None


class OwnerInfo(BaseModel):
    id: int
    phone: str
    first_name: str | None
    last_name: str | None


class SupportChatList(BaseModel):
    chats: list[SupportChatItem]
    next_cursor: datetime | None
```

- [ ] **Step 2: Write failing test**

Create `tests/integration/test_support_chats.py`:

```python
from datetime import datetime, timezone

import pytest
from passlib.context import CryptContext

from app.models.tables.support_agent import SupportAgent
from app.repositories.chat_repository import ChatRepository

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


@pytest.fixture
async def support_token(db_session, client):
    db_session.add(SupportAgent(login="ivy", password_hash=pwd.hash("openme"), display_name="Ivy", is_active=True))
    await db_session.commit()
    r = await client.post("/api/v1/support/login/", json={"login": "ivy", "password": "openme"})
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_support_chats_lists_active_chats(client, db_session, support_token):
    # Make a user and a chat with activity.
    from app.models.users.entities import User
    user = User(email="x@y.z", phone="+1000000004", password_hash="x",
                first_name="Alice", last_name="A.", patronymic=None,
                referral_code="REF004", referrer_id=None)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    cr = ChatRepository(db_session)
    chat = await cr.get_or_create_for_user(owner_user_id=user.id, chat_type="main")
    chat.last_message_at = datetime.now(timezone.utc)
    await db_session.commit()

    r = await client.get("/api/v1/support/chats/", headers={"Authorization": f"Bearer {support_token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(c["id"] == str(chat.id) for c in body["chats"])
    owner = next(c["owner"] for c in body["chats"] if c["id"] == str(chat.id))
    assert owner["phone"] == "+1000000004"


@pytest.mark.asyncio
async def test_support_chats_excludes_empty_by_default(client, db_session, support_token):
    from app.models.users.entities import User
    user = User(email="x@y.z", phone="+1000000005", password_hash="x",
                first_name=None, last_name=None, patronymic=None,
                referral_code="REF005", referrer_id=None)
    db_session.add(user)
    await db_session.commit()
    cr = ChatRepository(db_session)
    chat = await cr.get_or_create_for_user(owner_user_id=user.id, chat_type="main")
    # No bump → last_message_at is None

    r = await client.get("/api/v1/support/chats/", headers={"Authorization": f"Bearer {support_token}"})
    assert all(c["id"] != str(chat.id) for c in r.json()["chats"])
```

- [ ] **Step 3: Run (fails)**

Run: `uv run pytest tests/integration/test_support_chats.py -v`
Expected: 404.

- [ ] **Step 4: Add the listing endpoint to `app/api/routers/support.py`**

Append to the existing `support.py`:

```python
from datetime import datetime
from typing import Annotated

from fastapi import Query
from sqlalchemy import select

from app.api.deps.support_auth import get_current_support
from app.api.deps.subject_auth import SubjectRow
from app.models.dto.chat import OwnerInfo, SupportChatItem, SupportChatList
from app.models.users.entities import User
from app.repositories.chat_repository import ChatRepository


@router.get("/chats/", response_model=SupportChatList)
async def list_support_chats(
    chat_type: Annotated[str | None, Query(alias="type")] = None,
    before: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    include_empty: bool = Query(default=False),
    session: AsyncSession = Depends(get_async_session),
    _support: SubjectRow = Depends(get_current_support),
) -> SupportChatList:
    repo = ChatRepository(session)
    chats = await repo.list_active_for_support(
        chat_type=chat_type, limit=limit, before=before, include_empty=include_empty,
    )
    if not chats:
        return SupportChatList(chats=[], next_cursor=None)

    user_ids = {c.owner_user_id for c in chats}
    users_rows = await session.execute(select(User).where(User.id.in_(user_ids)))
    users = {u.id: u for u in users_rows.scalars().all()}

    items: list[SupportChatItem] = []
    for c in chats:
        u = users[c.owner_user_id]
        items.append(SupportChatItem(
            id=c.id, type=c.type,
            owner=OwnerInfo(id=u.id, phone=u.phone, first_name=u.first_name, last_name=u.last_name),
            last_message_at=c.last_message_at,
        ))

    next_cursor = chats[-1].last_message_at if len(chats) == limit else None
    return SupportChatList(chats=items, next_cursor=next_cursor)
```

- [ ] **Step 5: Run (passes)**

Run: `uv run pytest tests/integration/test_support_chats.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add app/api/routers/support.py app/models/dto/chat.py tests/integration/test_support_chats.py
git commit -m "support: /support/chats/ listing"
```

---

## Phase 8 — Internal endpoints (Go-facing)

### Task 8.1: Error classes + envelope handler

**Files:**
- Create: `app/services/errors.py`
- Create: `tests/integration/test_validation_envelope.py`

- [ ] **Step 1: Write failing test**

Create `tests/integration/test_validation_envelope.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_internal_validation_returns_envelope(client):
    # Missing X-Internal-Secret → 403, but body shape is still well-defined.
    r = await client.post("/internal/auth/ws-validate", json={"token": "x", "chat_type": "main", "chat_id_hint": ""})
    assert r.status_code == 403
    assert "detail" in r.json()


@pytest.mark.asyncio
async def test_pydantic_validation_becomes_400_with_code_reason(client):
    from app.core.config import settings
    headers = {"X-Internal-Secret": settings.internal_secret}
    # Missing required field "token".
    r = await client.post("/internal/auth/ws-validate", json={"chat_type": "main", "chat_id_hint": ""}, headers=headers)
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["code"] == "validation"
    assert "reason" in body
```

- [ ] **Step 2: Run (fails; endpoint doesn't exist yet but the second test will fail differently)**

Run: `uv run pytest tests/integration/test_validation_envelope.py -v`
Expected: 404 / FAIL on body shape.

- [ ] **Step 3: Write `app/services/errors.py`**

```python
class ChatError(Exception):
    """Business-rule error that maps to the Go-facing {code, reason} envelope."""

    def __init__(self, code: str, reason: str, http_status: int = 400):
        super().__init__(f"{code}: {reason}")
        self.code = code
        self.reason = reason
        self.http_status = http_status
```

- [ ] **Step 4: Add exception handlers in `app/main.py`**

In `app/main.py`, after `app = FastAPI(...)` line, add:

```python
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.services.errors import ChatError


@app.exception_handler(RequestValidationError)
async def _internal_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """For /internal/* routes, convert FastAPI's 422 into Go's expected
    {code: 'validation', reason: '<first error>'} envelope. Other routes get
    the default FastAPI 422."""
    if request.url.path.startswith("/internal/"):
        errs = exc.errors()
        first = errs[0] if errs else {"msg": "invalid request"}
        reason = first.get("msg", "invalid request")
        return JSONResponse(status_code=400, content={"code": "validation", "reason": reason})
    # default-shape fallback for non-internal routes (keep FastAPI behavior)
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(ChatError)
async def _chat_error_handler(request: Request, exc: ChatError) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content={"code": exc.code, "reason": exc.reason})
```

(We'll add the actual `internal.py` router in 8.2; the second test will keep failing until then. Continue.)

- [ ] **Step 5: Commit (partial — handlers in place, router pending)**

```bash
git add app/services/errors.py app/main.py tests/integration/test_validation_envelope.py
git commit -m "errors: ChatError + internal-envelope handlers"
```

### Task 8.2: Internal DTOs

**Files:**
- Create: `app/models/dto/internal.py`
- Create: `app/models/dto/message.py`
- Create: `app/models/dto/file.py`

- [ ] **Step 1: Write `app/models/dto/file.py`**

```python
from uuid import UUID

from pydantic import BaseModel


class FileMeta(BaseModel):
    file_id: UUID
    name: str
    mime: str
    size: int
    url: str
```

- [ ] **Step 2: Write `app/models/dto/message.py`**

```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.dto.file import FileMeta


class MessageResponse(BaseModel):
    id: UUID
    chat_id: UUID
    user_id: str
    role: str
    kind: str
    body: str | None = None
    file: FileMeta | None = None
    client_msg_id: str | None = None
    created_at: datetime


class MessageList(BaseModel):
    messages: list[MessageResponse]
    next_cursor: UUID | None
```

- [ ] **Step 3: Write `app/models/dto/internal.py`**

```python
from uuid import UUID

from pydantic import BaseModel


class WsValidateRequest(BaseModel):
    token: str
    chat_type: str
    chat_id_hint: str = ""


class WsValidateResponse(BaseModel):
    user_id: str
    role: str
    chat_id: UUID


class PersistMessageRequest(BaseModel):
    user_id: str
    role: str
    kind: str
    body: str | None = None
    file_id: UUID | None = None
    client_msg_id: str | None = None
```

- [ ] **Step 4: Commit**

```bash
git add app/models/dto/file.py app/models/dto/message.py app/models/dto/internal.py
git commit -m "dto: internal/message/file shapes"
```

### Task 8.3: Internal service (auth-validate + persist-message)

**Files:**
- Create: `app/services/internal_service.py`

- [ ] **Step 1: Write failing test**

Create `tests/integration/test_internal_service.py`:

```python
import pytest
from jose import jwt

from app.core.config import settings
from app.models.tables.support_agent import SupportAgent
from app.models.users.entities import User
from app.repositories.chat_repository import ChatRepository
from app.services.internal_service import InternalService
from app.services.errors import ChatError


def _make_token(claims: dict) -> str:
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


@pytest.fixture
async def user(db_session):
    u = User(email="a@b.c", phone="+1000000006", password_hash="x",
            first_name=None, last_name=None, patronymic=None,
            referral_code="REF006", referrer_id=None)
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


@pytest.mark.asyncio
async def test_ws_validate_lazy_creates_main_chat_for_user(db_session, user):
    svc = InternalService(db_session)
    tok = _make_token({"sub": f"user:{user.id}", "role": "user"})
    res = await svc.ws_validate(token=tok, chat_type="main", chat_id_hint="")
    assert res.user_id == f"user:{user.id}"
    assert res.role == "user"
    assert res.chat_id is not None


@pytest.mark.asyncio
async def test_ws_validate_user_idempotent(db_session, user):
    svc = InternalService(db_session)
    tok = _make_token({"sub": f"user:{user.id}", "role": "user"})
    a = await svc.ws_validate(token=tok, chat_type="main", chat_id_hint="")
    b = await svc.ws_validate(token=tok, chat_type="main", chat_id_hint="")
    assert a.chat_id == b.chat_id


@pytest.mark.asyncio
async def test_ws_validate_support_with_unknown_chat_404(db_session):
    agent = SupportAgent(login="kim", password_hash="x", display_name="Kim", is_active=True)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    svc = InternalService(db_session)
    tok = _make_token({"sub": f"support:{agent.id}", "role": "support"})
    import uuid as _u
    with pytest.raises(ChatError) as ei:
        await svc.ws_validate(token=tok, chat_type="main", chat_id_hint=str(_u.uuid4()))
    assert ei.value.http_status == 404


@pytest.mark.asyncio
async def test_ws_validate_chat_type_mismatch_400(db_session, user):
    cr = ChatRepository(db_session)
    chat = await cr.get_or_create_for_user(owner_user_id=user.id, chat_type="main")
    agent = SupportAgent(login="leo", password_hash="x", display_name="Leo", is_active=True)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    svc = InternalService(db_session)
    tok = _make_token({"sub": f"support:{agent.id}", "role": "support"})
    with pytest.raises(ChatError) as ei:
        await svc.ws_validate(token=tok, chat_type="bonus", chat_id_hint=str(chat.id))
    assert ei.value.http_status == 400


@pytest.mark.asyncio
async def test_persist_message_text_creates_row_and_bumps_chat(db_session, user):
    cr = ChatRepository(db_session)
    chat = await cr.get_or_create_for_user(owner_user_id=user.id, chat_type="main")

    svc = InternalService(db_session)
    msg = await svc.persist_message(
        chat_id=chat.id,
        user_id=f"user:{user.id}",
        role="user",
        kind="message",
        body="hello",
        file_id=None,
        client_msg_id="c-1",
    )
    assert msg.kind == "message"
    assert msg.body == "hello"
    assert msg.user_id == f"user:{user.id}"

    refreshed = await cr.get_by_id(chat.id)
    assert refreshed.last_message_at is not None


@pytest.mark.asyncio
async def test_persist_message_idempotent_does_not_rebump(db_session, user):
    cr = ChatRepository(db_session)
    chat = await cr.get_or_create_for_user(owner_user_id=user.id, chat_type="main")
    svc = InternalService(db_session)
    a = await svc.persist_message(chat_id=chat.id, user_id=f"user:{user.id}", role="user",
                                  kind="message", body="x", file_id=None, client_msg_id="c-2")
    first_bump = (await cr.get_by_id(chat.id)).last_message_at
    b = await svc.persist_message(chat_id=chat.id, user_id=f"user:{user.id}", role="user",
                                  kind="message", body="x", file_id=None, client_msg_id="c-2")
    second_bump = (await cr.get_by_id(chat.id)).last_message_at
    assert a.id == b.id
    assert first_bump == second_bump


@pytest.mark.asyncio
async def test_persist_oversize_body_413(db_session, user, monkeypatch):
    monkeypatch.setattr(settings, "max_message_bytes", 10)
    cr = ChatRepository(db_session)
    chat = await cr.get_or_create_for_user(owner_user_id=user.id, chat_type="main")
    svc = InternalService(db_session)
    with pytest.raises(ChatError) as ei:
        await svc.persist_message(chat_id=chat.id, user_id=f"user:{user.id}", role="user",
                                  kind="message", body="x" * 11, file_id=None, client_msg_id="c-3")
    assert ei.value.http_status == 413
    assert ei.value.code == "payload_too_large"


@pytest.mark.asyncio
async def test_persist_file_not_in_chat_400(db_session, user):
    """file_id exists, but bound to a *different* chat → 400 validation."""
    from app.repositories.file_repository import FileRepository

    cr = ChatRepository(db_session)
    chat_a = await cr.get_or_create_for_user(owner_user_id=user.id, chat_type="main")
    chat_b = await cr.get_or_create_for_user(owner_user_id=user.id, chat_type="bonus")

    fr = FileRepository(db_session)
    file_b = await fr.create(
        chat_id=chat_b.id, uploader_subject_type="user", uploader_subject_id=user.id,
        original_name="x.txt", mime_type="text/plain", size_bytes=1,
        minio_key=f"chats/{chat_b.id}/k",
    )
    await db_session.commit()

    svc = InternalService(db_session)
    with pytest.raises(ChatError) as ei:
        await svc.persist_message(
            chat_id=chat_a.id, user_id=f"user:{user.id}", role="user",
            kind="file", body=None, file_id=file_b.id, client_msg_id="c-4",
        )
    assert ei.value.http_status == 400
    assert "file not in chat" in ei.value.reason
```

- [ ] **Step 2: Run (fails)**

Run: `uv run pytest tests/integration/test_internal_service.py -v`
Expected: ImportError / FAIL.

- [ ] **Step 3: Write `app/services/internal_service.py`**

```python
from uuid import UUID

from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.subject_auth import parse_subject_claim
from app.core.config import settings
from app.models.dto.file import FileMeta
from app.models.dto.internal import WsValidateResponse
from app.models.dto.message import MessageResponse
from app.models.tables.support_agent import SupportAgent
from app.models.users.entities import User
from app.repositories.chat_repository import ChatRepository
from app.repositories.file_repository import FileRepository
from app.repositories.message_repository import MessageRepository
from app.services.errors import ChatError


_VALID_CHAT_TYPES = {"main", "bonus"}
_VALID_KINDS = {"message", "file"}


class InternalService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def ws_validate(self, *, token: str, chat_type: str, chat_id_hint: str) -> WsValidateResponse:
        try:
            payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        except JWTError as e:
            raise ChatError("validation", f"invalid token: {e}", http_status=401)

        sub_claim = payload.get("sub")
        if not isinstance(sub_claim, str):
            raise ChatError("validation", "missing sub claim", http_status=401)
        try:
            subject = parse_subject_claim(sub_claim)
        except ValueError as e:
            raise ChatError("validation", str(e), http_status=401)

        if chat_type not in _VALID_CHAT_TYPES:
            raise ChatError("validation", f"invalid chat_type: {chat_type!r}", http_status=400)

        if subject.type == "user":
            row = await self._session.execute(select(User).where(User.id == subject.id))
            if row.scalar_one_or_none() is None:
                raise ChatError("validation", "user not found", http_status=401)

            cr = ChatRepository(self._session)
            chat = await cr.get_or_create_for_user(owner_user_id=subject.id, chat_type=chat_type)
            return WsValidateResponse(user_id=sub_claim, role="user", chat_id=chat.id)

        # subject.type == "support"
        row = await self._session.execute(select(SupportAgent).where(SupportAgent.id == subject.id))
        agent = row.scalar_one_or_none()
        if agent is None or not agent.is_active:
            raise ChatError("validation", "support agent not found or inactive", http_status=401)

        if not chat_id_hint:
            raise ChatError("validation", "chat_id_hint required for support", http_status=400)
        try:
            hint_uuid = UUID(chat_id_hint)
        except ValueError:
            raise ChatError("validation", "chat_id_hint not a UUID", http_status=400)

        cr = ChatRepository(self._session)
        chat = await cr.get_by_id(hint_uuid)
        if chat is None:
            raise ChatError("validation", "chat not found", http_status=404)
        if chat.type != chat_type:
            raise ChatError("validation", "chat_type mismatch", http_status=400)
        return WsValidateResponse(user_id=sub_claim, role="support", chat_id=chat.id)

    async def persist_message(
        self,
        *,
        chat_id: UUID,
        user_id: str,
        role: str,
        kind: str,
        body: str | None,
        file_id: UUID | None,
        client_msg_id: str | None,
    ) -> MessageResponse:
        # Parse and verify subject.
        try:
            subject = parse_subject_claim(user_id)
        except ValueError as e:
            raise ChatError("validation", str(e), http_status=401)

        if kind not in _VALID_KINDS:
            raise ChatError("unsupported_type", f"unknown kind: {kind!r}", http_status=400)

        cr = ChatRepository(self._session)
        chat = await cr.get_by_id(chat_id)
        if chat is None:
            raise ChatError("validation", "chat not found", http_status=404)

        if subject.type == "user":
            if chat.owner_user_id != subject.id:
                raise ChatError("validation", "not a participant", http_status=403)
        else:
            row = await self._session.execute(select(SupportAgent).where(SupportAgent.id == subject.id))
            agent = row.scalar_one_or_none()
            if agent is None or not agent.is_active:
                raise ChatError("validation", "support agent inactive", http_status=403)

        # Per-kind validation.
        if kind == "message":
            if not body:
                raise ChatError("validation", "body required for kind=message", http_status=400)
            if len(body.encode("utf-8")) > settings.max_message_bytes:
                raise ChatError("payload_too_large", "body exceeds max_message_bytes", http_status=413)
            file_id = None
        else:  # kind == "file"
            if file_id is None:
                raise ChatError("validation", "file_id required for kind=file", http_status=400)
            file_row = await FileRepository(self._session).get_by_id(file_id)
            if file_row is None or file_row.chat_id != chat_id:
                raise ChatError("validation", "file not in chat", http_status=400)
            body = None

        msg_repo = MessageRepository(self._session)
        msg, created = await msg_repo.insert_or_get(
            chat_id=chat_id,
            sender_subject_type=subject.type,
            sender_subject_id=subject.id,
            kind=kind,
            body=body,
            file_id=file_id,
            client_msg_id=client_msg_id,
        )
        if created:
            await cr.bump_last_message_at(chat_id)
        await self._session.commit()

        # Build response.
        file_meta: FileMeta | None = None
        if msg.kind == "file":
            file_row = await FileRepository(self._session).get_by_id(msg.file_id)
            assert file_row is not None
            file_meta = FileMeta(
                file_id=file_row.id, name=file_row.original_name,
                mime=file_row.mime_type, size=file_row.size_bytes,
                url=f"/api/v1/files/{file_row.id}/",
            )

        return MessageResponse(
            id=msg.id, chat_id=msg.chat_id, user_id=user_id, role=role,
            kind=msg.kind, body=msg.body, file=file_meta,
            client_msg_id=msg.client_msg_id, created_at=msg.created_at,
        )
```

- [ ] **Step 4: Run (passes)**

Run: `uv run pytest tests/integration/test_internal_service.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/internal_service.py tests/integration/test_internal_service.py
git commit -m "internal: service for ws-validate + persist-message"
```

### Task 8.4: Internal router

**Files:**
- Create: `app/api/routers/internal.py`

- [ ] **Step 1: Write failing test**

Create `tests/integration/test_internal_ws_validate.py`:

```python
import pytest
from jose import jwt

from app.core.config import settings
from app.models.users.entities import User


def _make_token(claims: dict) -> str:
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


@pytest.fixture
async def secret_headers():
    return {"X-Internal-Secret": settings.internal_secret}


@pytest.mark.asyncio
async def test_ws_validate_user_lazy_creates(client, db_session, secret_headers):
    u = User(email="a@b.c", phone="+1000000007", password_hash="x",
            first_name=None, last_name=None, patronymic=None,
            referral_code="REF007", referrer_id=None)
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)

    tok = _make_token({"sub": f"user:{u.id}", "role": "user"})
    r = await client.post("/internal/auth/ws-validate",
                          json={"token": tok, "chat_type": "main", "chat_id_hint": ""},
                          headers=secret_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == f"user:{u.id}"
    assert body["role"] == "user"
    assert body["chat_id"]


@pytest.mark.asyncio
async def test_ws_validate_missing_secret_403(client):
    r = await client.post("/internal/auth/ws-validate",
                          json={"token": "x", "chat_type": "main", "chat_id_hint": ""})
    assert r.status_code == 403
```

Create `tests/integration/test_internal_messages.py`:

```python
import pytest
from jose import jwt

from app.core.config import settings
from app.models.users.entities import User
from app.repositories.chat_repository import ChatRepository


def _make_token(uid: int) -> str:
    return jwt.encode({"sub": f"user:{uid}", "role": "user"}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


@pytest.mark.asyncio
async def test_persist_text_happy_path(client, db_session):
    u = User(email="a@b.c", phone="+1000000008", password_hash="x",
            first_name=None, last_name=None, patronymic=None,
            referral_code="REF008", referrer_id=None)
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    cr = ChatRepository(db_session)
    chat = await cr.get_or_create_for_user(owner_user_id=u.id, chat_type="main")

    r = await client.post(
        f"/internal/chats/{chat.id}/messages",
        json={
            "user_id": f"user:{u.id}", "role": "user",
            "kind": "message", "body": "hi", "client_msg_id": "c-1",
        },
        headers={"X-Internal-Secret": settings.internal_secret},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "message" and body["body"] == "hi"
    assert body["user_id"] == f"user:{u.id}"
    assert body["client_msg_id"] == "c-1"


@pytest.mark.asyncio
async def test_persist_oversize_returns_413_envelope(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "max_message_bytes", 5)
    u = User(email="a@b.c", phone="+1000000009", password_hash="x",
            first_name=None, last_name=None, patronymic=None,
            referral_code="REF009", referrer_id=None)
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    cr = ChatRepository(db_session)
    chat = await cr.get_or_create_for_user(owner_user_id=u.id, chat_type="main")
    r = await client.post(
        f"/internal/chats/{chat.id}/messages",
        json={"user_id": f"user:{u.id}", "role": "user", "kind": "message", "body": "way too long"},
        headers={"X-Internal-Secret": settings.internal_secret},
    )
    assert r.status_code == 413
    assert r.json()["code"] == "payload_too_large"
```

- [ ] **Step 2: Run (fails — endpoints don't exist)**

Run: `uv run pytest tests/integration/test_internal_ws_validate.py tests/integration/test_internal_messages.py -v`
Expected: 404 / FAIL.

- [ ] **Step 3: Write `app/api/routers/internal.py`**

```python
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.internal_secret import internal_secret_required
from app.core.database import get_async_session
from app.models.dto.internal import (
    PersistMessageRequest,
    WsValidateRequest,
    WsValidateResponse,
)
from app.models.dto.message import MessageResponse
from app.services.internal_service import InternalService


router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(internal_secret_required)])


@router.post("/auth/ws-validate", response_model=WsValidateResponse)
async def ws_validate(
    payload: WsValidateRequest,
    session: AsyncSession = Depends(get_async_session),
) -> WsValidateResponse:
    svc = InternalService(session)
    return await svc.ws_validate(token=payload.token, chat_type=payload.chat_type, chat_id_hint=payload.chat_id_hint)


@router.post("/chats/{chat_id}/messages", response_model=MessageResponse)
async def persist_message(
    chat_id: UUID,
    payload: PersistMessageRequest,
    session: AsyncSession = Depends(get_async_session),
) -> MessageResponse:
    svc = InternalService(session)
    return await svc.persist_message(
        chat_id=chat_id,
        user_id=payload.user_id,
        role=payload.role,
        kind=payload.kind,
        body=payload.body,
        file_id=payload.file_id,
        client_msg_id=payload.client_msg_id,
    )
```

- [ ] **Step 4: Mount the router in `app/main.py`**

In `app/main.py`, after `app.include_router(api_router)`, add:

```python
from app.api.routers.internal import router as internal_router

app.include_router(internal_router)  # mounted at /internal/*, no /api/v1 prefix
```

(Place the import at the top with the other imports if you prefer.)

- [ ] **Step 5: Run (passes)**

Run: `uv run pytest tests/integration/test_internal_ws_validate.py tests/integration/test_internal_messages.py tests/integration/test_validation_envelope.py -v`
Expected: 5+ passed.

- [ ] **Step 6: Commit**

```bash
git add app/api/routers/internal.py app/main.py tests/integration/test_internal_ws_validate.py tests/integration/test_internal_messages.py
git commit -m "internal: /internal/auth/ws-validate + /internal/chats/{id}/messages"
```

---

## Phase 9 — Public chat endpoints

### Task 9.1: Replace `chats.py` stub

**Files:** Modify `app/api/routers/chats.py`

- [ ] **Step 1: Write failing tests**

Create `tests/integration/test_chats_public.py`:

```python
import pytest
from jose import jwt

from app.core.config import settings
from app.models.users.entities import User
from app.services.auth_service import AuthService


@pytest.fixture
async def user_with_token(db_session, client):
    u = User(email="a@b.c", phone="+1000000010", password_hash="x",
            first_name=None, last_name=None, patronymic=None,
            referral_code="REF010", referrer_id=None)
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)

    svc = AuthService(db_session)
    token = svc._generate_access_token(user_id=u.id)
    return u, token


@pytest.mark.asyncio
async def test_list_chats_lazy_creates_main(user_with_token, client):
    user, token = user_with_token
    r = await client.get("/api/v1/chats/", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    types = {c["type"] for c in body}
    assert "main" in types


@pytest.mark.asyncio
async def test_post_chats_opens_bonus(user_with_token, client):
    user, token = user_with_token
    r = await client.post("/api/v1/chats/", json={"type": "bonus"}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201 or r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "bonus"

    # GET now returns both.
    r2 = await client.get("/api/v1/chats/", headers={"Authorization": f"Bearer {token}"})
    types = {c["type"] for c in r2.json()}
    assert types == {"main", "bonus"}


@pytest.mark.asyncio
async def test_history_cursor_pagination(user_with_token, client, db_session):
    user, token = user_with_token
    from app.repositories.chat_repository import ChatRepository
    from app.repositories.message_repository import MessageRepository
    cr = ChatRepository(db_session)
    chat = await cr.get_or_create_for_user(owner_user_id=user.id, chat_type="main")
    mr = MessageRepository(db_session)
    ids = []
    for i in range(5):
        m, _ = await mr.insert_or_get(
            chat_id=chat.id, sender_subject_type="user", sender_subject_id=user.id,
            kind="message", body=f"m{i}", file_id=None, client_msg_id=f"c{i}",
        )
        ids.append(str(m.id))
    await db_session.commit()

    r = await client.get(
        f"/api/v1/chats/{chat.id}/messages/?limit=3",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["messages"]) == 3
    assert body["next_cursor"] is not None

    r2 = await client.get(
        f"/api/v1/chats/{chat.id}/messages/?limit=3&before={body['next_cursor']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert len(r2.json()["messages"]) == 2
    assert r2.json()["next_cursor"] is None


@pytest.mark.asyncio
async def test_history_rejects_non_owner(user_with_token, client, db_session):
    user, token = user_with_token
    # Make a second user with their own chat.
    u2 = User(email="b@b.c", phone="+1000000011", password_hash="x",
            first_name=None, last_name=None, patronymic=None,
            referral_code="REF011", referrer_id=None)
    db_session.add(u2)
    await db_session.commit()
    await db_session.refresh(u2)
    from app.repositories.chat_repository import ChatRepository
    cr = ChatRepository(db_session)
    other_chat = await cr.get_or_create_for_user(owner_user_id=u2.id, chat_type="main")

    r = await client.get(
        f"/api/v1/chats/{other_chat.id}/messages/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
```

- [ ] **Step 2: Run (fails — stub returns not_implemented)**

Run: `uv run pytest tests/integration/test_chats_public.py -v`
Expected: FAIL (501 or schema mismatch).

- [ ] **Step 3: Replace `app/api/routers/chats.py`**

```python
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.subject_auth import SubjectRow, get_current_subject
from app.core.database import get_async_session
from app.models.dto.chat import ChatCreate, ChatResponse
from app.models.dto.file import FileMeta
from app.models.dto.message import MessageList, MessageResponse
from app.repositories.chat_repository import ChatRepository
from app.repositories.file_repository import FileRepository
from app.repositories.message_repository import MessageRepository


router = APIRouter(prefix="/chats", tags=["chats"])


@router.get("/", response_model=list[ChatResponse])
async def list_chats(
    subject: SubjectRow = Depends(get_current_subject),
    session: AsyncSession = Depends(get_async_session),
) -> list[ChatResponse]:
    if subject.subject.type != "user" or subject.user is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user only")
    repo = ChatRepository(session)
    # Lazy-create main if missing
    await repo.get_or_create_for_user(owner_user_id=subject.user.id, chat_type="main")
    rows = await repo.list_for_user(subject.user.id)
    return [ChatResponse(id=c.id, type=c.type, last_message_at=c.last_message_at) for c in rows]


@router.post("/", response_model=ChatResponse)
async def open_chat(
    payload: ChatCreate,
    subject: SubjectRow = Depends(get_current_subject),
    session: AsyncSession = Depends(get_async_session),
) -> ChatResponse:
    if subject.subject.type != "user" or subject.user is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user only")
    if payload.type not in {"main", "bonus"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid chat type")
    repo = ChatRepository(session)
    chat = await repo.get_or_create_for_user(owner_user_id=subject.user.id, chat_type=payload.type)
    return ChatResponse(id=chat.id, type=chat.type, last_message_at=chat.last_message_at)


@router.get("/{chat_id}/messages/", response_model=MessageList)
async def list_chat_messages(
    chat_id: UUID,
    before: UUID | None = Query(default=None),
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    subject: SubjectRow = Depends(get_current_subject),
    session: AsyncSession = Depends(get_async_session),
) -> MessageList:
    chat_repo = ChatRepository(session)
    chat = await chat_repo.get_by_id(chat_id)
    if chat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="chat not found")
    if subject.subject.type == "user":
        if subject.user is None or chat.owner_user_id != subject.user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not a participant")
    else:
        if subject.support is None or not subject.support.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="support inactive")

    msg_repo = MessageRepository(session)
    rows = await msg_repo.list_history(chat_id=chat_id, limit=limit, before_id=before)

    file_ids = {m.file_id for m in rows if m.file_id is not None}
    files = {}
    if file_ids:
        file_repo = FileRepository(session)
        for fid in file_ids:
            f = await file_repo.get_by_id(fid)
            if f is not None:
                files[f.id] = f

    items = []
    for m in rows:
        file_meta: FileMeta | None = None
        if m.kind == "file" and m.file_id is not None and m.file_id in files:
            f = files[m.file_id]
            file_meta = FileMeta(file_id=f.id, name=f.original_name, mime=f.mime_type, size=f.size_bytes,
                                 url=f"/api/v1/files/{f.id}/")
        items.append(MessageResponse(
            id=m.id, chat_id=m.chat_id,
            user_id=f"{m.sender_subject_type}:{m.sender_subject_id}",
            role=m.sender_subject_type,
            kind=m.kind, body=m.body, file=file_meta,
            client_msg_id=m.client_msg_id, created_at=m.created_at,
        ))

    next_cursor = rows[-1].id if len(rows) == limit else None
    return MessageList(messages=items, next_cursor=next_cursor)
```

- [ ] **Step 4: Run (passes)**

Run: `uv run pytest tests/integration/test_chats_public.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/api/routers/chats.py tests/integration/test_chats_public.py
git commit -m "chats: replace stub with list/open/history endpoints"
```

---

## Phase 10 — Files (MinIO + endpoints)

### Task 10.1: MinIO client factory + lifespan

**Files:**
- Create: `app/core/minio_client.py`
- Modify: `app/main.py`

- [ ] **Step 1: Write `app/core/minio_client.py`**

```python
from minio import Minio

from app.core.config import settings


def build_minio_client() -> Minio:
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def ensure_bucket(client: Minio, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
```

- [ ] **Step 2: Hook into `lifespan` in `app/main.py`**

Edit `app/main.py`:

```python
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI

from app.api.main_router import api_router
from app.core.config import settings
from app.core.minio_client import build_minio_client, ensure_bucket


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = redis.Redis(host="localhost", port=6379, decode_responses=True)
    app.state.minio = build_minio_client()
    ensure_bucket(app.state.minio, settings.minio_bucket)
    yield
    await app.state.redis.close()
```

Leave the existing FastAPI app definition and the `lifespan=lifespan` argument untouched.

- [ ] **Step 3: Commit**

```bash
git add app/core/minio_client.py app/main.py
git commit -m "minio: client factory + bucket ensure in lifespan"
```

### Task 10.2: File service

**Files:**
- Create: `app/services/file_service.py`

- [ ] **Step 1: Write failing test (using a mocked MinIO client)**

Create `tests/integration/test_file_service.py`:

```python
import io

import pytest
from unittest.mock import MagicMock

from app.repositories.chat_repository import ChatRepository
from app.services.errors import ChatError
from app.services.file_service import FileService


class FakeMinIO:
    def __init__(self):
        self.put_calls = []
        self.objects = {}

    def put_object(self, bucket, key, data, length, content_type=None):
        self.put_calls.append((bucket, key, length, content_type))
        self.objects[(bucket, key)] = data.read() if hasattr(data, "read") else data

    def get_object(self, bucket, key):
        body = self.objects.get((bucket, key), b"")

        class _Resp:
            def __init__(self, b): self._b = b; self.headers = {}
            def stream(self, n): yield self._b
            def read(self, n=-1): return self._b
            def close(self): pass
            def release_conn(self): pass

        return _Resp(body)

    def remove_object(self, bucket, key):
        self.objects.pop((bucket, key), None)


@pytest.fixture
async def chat_and_user(db_session):
    from app.models.users.entities import User
    u = User(email="a@b.c", phone="+1000000012", password_hash="x",
            first_name=None, last_name=None, patronymic=None,
            referral_code="REF012", referrer_id=None)
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    cr = ChatRepository(db_session)
    chat = await cr.get_or_create_for_user(owner_user_id=u.id, chat_type="main")
    return chat, u


@pytest.mark.asyncio
async def test_upload_creates_row_and_puts_object(db_session, chat_and_user):
    chat, user = chat_and_user
    fake = FakeMinIO()
    svc = FileService(db_session, fake, bucket="chat-files-test", max_bytes=10_000)
    data = io.BytesIO(b"abc")
    f = await svc.upload(
        chat_id=chat.id, uploader_subject_type="user", uploader_subject_id=user.id,
        original_name="hello.txt", mime_type="text/plain", size_bytes=3, stream=data,
    )
    assert f.minio_key.startswith(f"chats/{chat.id}/")
    assert len(fake.put_calls) == 1


@pytest.mark.asyncio
async def test_upload_too_large_413(db_session, chat_and_user):
    chat, user = chat_and_user
    fake = FakeMinIO()
    svc = FileService(db_session, fake, bucket="b", max_bytes=2)
    with pytest.raises(ChatError) as ei:
        await svc.upload(
            chat_id=chat.id, uploader_subject_type="user", uploader_subject_id=user.id,
            original_name="big.bin", mime_type="application/octet-stream", size_bytes=10, stream=io.BytesIO(b"x" * 10),
        )
    assert ei.value.http_status == 413


@pytest.mark.asyncio
async def test_upload_db_failure_cleans_minio_object(db_session, chat_and_user, monkeypatch):
    """If the DB INSERT raises after MinIO put, the object must be removed."""
    chat, user = chat_and_user
    fake = FakeMinIO()
    svc = FileService(db_session, fake, bucket="b", max_bytes=10_000)

    # Force FileRepository.create to raise after MinIO put.
    from app.repositories import file_repository as fr_mod

    async def boom(self, **kw):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(fr_mod.FileRepository, "create", boom)

    with pytest.raises(RuntimeError):
        await svc.upload(
            chat_id=chat.id, uploader_subject_type="user", uploader_subject_id=user.id,
            original_name="x.txt", mime_type="text/plain", size_bytes=3, stream=io.BytesIO(b"abc"),
        )
    assert fake.objects == {}  # MinIO cleaned up
```

- [ ] **Step 2: Run (fails)**

Run: `uv run pytest tests/integration/test_file_service.py -v`
Expected: ImportError.

- [ ] **Step 3: Write `app/services/file_service.py`**

```python
import asyncio
import uuid
from typing import BinaryIO

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables.file import File
from app.repositories.file_repository import FileRepository
from app.services.errors import ChatError


class FileService:
    def __init__(self, session: AsyncSession, minio_client, bucket: str, max_bytes: int):
        self._session = session
        self._minio = minio_client
        self._bucket = bucket
        self._max_bytes = max_bytes

    async def upload(
        self,
        *,
        chat_id: uuid.UUID,
        uploader_subject_type: str,
        uploader_subject_id: int,
        original_name: str,
        mime_type: str,
        size_bytes: int,
        stream: BinaryIO,
    ) -> File:
        if size_bytes > self._max_bytes:
            raise ChatError("payload_too_large", "file exceeds max_file_bytes", http_status=413)

        file_id = uuid.uuid4()
        minio_key = f"chats/{chat_id}/{file_id}"

        # Streaming put — synchronous SDK; run in threadpool.
        await asyncio.to_thread(
            self._minio.put_object, self._bucket, minio_key, stream, size_bytes, content_type=mime_type,
        )

        try:
            repo = FileRepository(self._session)
            f = await repo.create(
                chat_id=chat_id,
                uploader_subject_type=uploader_subject_type,
                uploader_subject_id=uploader_subject_id,
                original_name=original_name,
                mime_type=mime_type,
                size_bytes=size_bytes,
                minio_key=minio_key,
            )
            # Override default UUID with our pre-generated one for predictable key
            f.id = file_id
            await self._session.commit()
            await self._session.refresh(f)
            return f
        except Exception:
            await self._session.rollback()
            try:
                await asyncio.to_thread(self._minio.remove_object, self._bucket, minio_key)
            except Exception:
                pass
            raise

    async def download_stream(self, file_id: uuid.UUID):
        """Returns (file_row, generator). Caller iterates the generator to stream bytes."""
        repo = FileRepository(self._session)
        f = await repo.get_by_id(file_id)
        if f is None:
            raise ChatError("validation", "file not found", http_status=404)
        # Open the MinIO response synchronously; the iterator yields chunks.
        response = await asyncio.to_thread(self._minio.get_object, self._bucket, f.minio_key)

        async def _agen():
            try:
                for chunk in response.stream(8 * 1024):
                    yield chunk
            finally:
                response.close()
                response.release_conn()

        return f, _agen()
```

(Note: the test patches the `id` after creation because the repo generates a UUID via the model default. The service constructs `minio_key` from a pre-generated `file_id` to avoid a race; we set `f.id = file_id` after the insert. This is a small inelegance acknowledged.)

- [ ] **Step 4: Run (passes)**

Run: `uv run pytest tests/integration/test_file_service.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/file_service.py tests/integration/test_file_service.py
git commit -m "files: service for upload + download streaming"
```

### Task 10.3: Files router

**Files:** Modify `app/api/routers/files.py`

- [ ] **Step 1: Write failing test**

Create `tests/integration/test_files_endpoints.py`:

```python
import io

import pytest

from app.core.config import settings
from app.models.users.entities import User
from app.repositories.chat_repository import ChatRepository
from app.services.auth_service import AuthService


@pytest.fixture
async def user_and_chat(db_session):
    u = User(email="a@b.c", phone="+1000000013", password_hash="x",
            first_name=None, last_name=None, patronymic=None,
            referral_code="REF013", referrer_id=None)
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    cr = ChatRepository(db_session)
    chat = await cr.get_or_create_for_user(owner_user_id=u.id, chat_type="main")
    svc = AuthService(db_session)
    token = svc._generate_access_token(user_id=u.id)
    return u, chat, token


@pytest.mark.asyncio
async def test_upload_then_download(client, user_and_chat, monkeypatch):
    user, chat, token = user_and_chat

    # Mock MinIO via app.state on the FastAPI instance.
    from app.main import app

    class FakeMinIO:
        def __init__(self):
            self.objects = {}
        def put_object(self, bucket, key, data, length, content_type=None):
            self.objects[(bucket, key)] = data.read() if hasattr(data, "read") else data
        def get_object(self, bucket, key):
            body = self.objects.get((bucket, key), b"")
            class _Resp:
                def __init__(self, b): self._b = b
                def stream(self, n): yield self._b
                def close(self): pass
                def release_conn(self): pass
            return _Resp(body)
        def remove_object(self, bucket, key):
            self.objects.pop((bucket, key), None)
        def bucket_exists(self, bucket): return True
        def make_bucket(self, bucket): pass

    fake = FakeMinIO()
    monkeypatch.setattr(app.state, "minio", fake, raising=False)
    monkeypatch.setattr(settings, "minio_bucket", "test-bucket")

    files = {"file": ("hi.txt", io.BytesIO(b"hello"), "text/plain")}
    data = {"chat_id": str(chat.id)}
    r = await client.post("/api/v1/files/", files=files, data=data,
                          headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "hi.txt" and body["mime"] == "text/plain" and body["size"] == 5
    file_id = body["file_id"]

    r2 = await client.get(f"/api/v1/files/{file_id}/", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200
    assert r2.headers["content-type"].startswith("text/plain")
    assert r2.content == b"hello"


@pytest.mark.asyncio
async def test_upload_rejects_non_participant(client, user_and_chat, db_session, monkeypatch):
    user, chat, _token = user_and_chat
    # Make a second user and token.
    u2 = User(email="b@b.c", phone="+1000000014", password_hash="x",
            first_name=None, last_name=None, patronymic=None,
            referral_code="REF014", referrer_id=None)
    db_session.add(u2)
    await db_session.commit()
    await db_session.refresh(u2)
    svc = AuthService(db_session)
    other_token = svc._generate_access_token(user_id=u2.id)

    files = {"file": ("a.txt", io.BytesIO(b"x"), "text/plain")}
    data = {"chat_id": str(chat.id)}
    r = await client.post("/api/v1/files/", files=files, data=data,
                          headers={"Authorization": f"Bearer {other_token}"})
    assert r.status_code == 403
```

- [ ] **Step 2: Run (fails)**

Run: `uv run pytest tests/integration/test_files_endpoints.py -v`
Expected: FAIL (existing stub returns 501).

- [ ] **Step 3: Replace `app/api/routers/files.py`**

```python
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.subject_auth import SubjectRow, get_current_subject
from app.core.config import settings
from app.core.database import get_async_session
from app.models.dto.file import FileMeta
from app.repositories.chat_repository import ChatRepository
from app.services.file_service import FileService


router = APIRouter(prefix="/files", tags=["files"])


@router.post("/", response_model=FileMeta, status_code=status.HTTP_201_CREATED)
async def upload_file(
    request: Request,
    chat_id: UUID = Form(...),
    file: UploadFile = File(...),
    subject: SubjectRow = Depends(get_current_subject),
    session: AsyncSession = Depends(get_async_session),
) -> FileMeta:
    # Authorize against chat.
    chat = await ChatRepository(session).get_by_id(chat_id)
    if chat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="chat not found")
    if subject.subject.type == "user":
        if subject.user is None or chat.owner_user_id != subject.user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not a participant")
    else:
        if subject.support is None or not subject.support.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="support inactive")

    minio_client = request.app.state.minio
    svc = FileService(session, minio_client, bucket=settings.minio_bucket, max_bytes=settings.max_file_bytes)

    # Determine declared size — UploadFile.size may be None if streamed; fall back to reading.
    size = file.size
    if size is None:
        body = await file.read()
        size = len(body)
        import io as _io
        stream = _io.BytesIO(body)
    else:
        stream = file.file

    f = await svc.upload(
        chat_id=chat_id,
        uploader_subject_type=subject.subject.type,
        uploader_subject_id=subject.subject.id,
        original_name=file.filename or "untitled",
        mime_type=file.content_type or "application/octet-stream",
        size_bytes=size,
        stream=stream,
    )
    return FileMeta(file_id=f.id, name=f.original_name, mime=f.mime_type, size=f.size_bytes,
                    url=f"/api/v1/files/{f.id}/")


@router.get("/{file_id}/")
async def download_file(
    file_id: UUID,
    request: Request,
    subject: SubjectRow = Depends(get_current_subject),
    session: AsyncSession = Depends(get_async_session),
) -> StreamingResponse:
    from app.repositories.file_repository import FileRepository
    f = await FileRepository(session).get_by_id(file_id)
    if f is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")

    chat = await ChatRepository(session).get_by_id(f.chat_id)
    if chat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="chat not found")
    if subject.subject.type == "user":
        if subject.user is None or chat.owner_user_id != subject.user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not a participant")
    else:
        if subject.support is None or not subject.support.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="support inactive")

    minio_client = request.app.state.minio
    svc = FileService(session, minio_client, bucket=settings.minio_bucket, max_bytes=settings.max_file_bytes)
    _, agen = await svc.download_stream(file_id)

    safe_name = f.original_name.replace('"', '')
    headers = {
        "Content-Length": str(f.size_bytes),
        "Content-Disposition": f'inline; filename="{safe_name}"',
        "Cache-Control": "private, max-age=0",
    }
    return StreamingResponse(agen, media_type=f.mime_type, headers=headers)
```

- [ ] **Step 4: Run (passes)**

Run: `uv run pytest tests/integration/test_files_endpoints.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add app/api/routers/files.py tests/integration/test_files_endpoints.py
git commit -m "files: replace stub with multipart upload + streaming download"
```

---

## Phase 11 — Go-side rename `sidequest` → `bonus`

These tasks happen in the **`InsurancePlatform/`** Go repository. Switch directories.

### Task 11.1: Rename comments in Go source

**Files:**
- Modify: `InsurancePlatform/internal/auth/identity.go`
- Modify: `InsurancePlatform/internal/auth/client.go`
- Modify: `InsurancePlatform/internal/server/ws_handler.go`

- [ ] **Step 1: Edit `identity.go`**

Change line 20 from:
```go
	ChatType string // "main" | "sidequest"
```
to:
```go
	ChatType string // "main" | "bonus"
```

- [ ] **Step 2: Edit `client.go`**

Change the doc-comment line that reads:
```
//     {"token": "...", "chat_type": "main|sidequest", "chat_id_hint": "..."?}
```
to:
```
//     {"token": "...", "chat_type": "main|bonus", "chat_id_hint": "..."?}
```

- [ ] **Step 3: Edit `ws_handler.go`**

Change the line:
```
//     - chat_type from query "type" ("main" | "sidequest").
```
to:
```
//     - chat_type from query "type" ("main" | "bonus").
```

- [ ] **Step 4: Verify Go builds and tests pass**

From `InsurancePlatform/`:
```bash
go build ./...
go test ./... -count=1 -timeout 60s
```
Expected: clean build, all tests pass.

- [ ] **Step 5: Commit (in `InsurancePlatform/`)**

```bash
git add internal/auth/identity.go internal/auth/client.go internal/server/ws_handler.go
git commit -m "rename sidequest -> bonus in comments (match Python design)"
```

### Task 11.2: Rename in frontend-integration doc

**Files:**
- Modify: `InsurancePlatform/docs/frontend-integration.ru.md`

- [ ] **Step 1: Find the two lines**

Run from `InsurancePlatform/`:
```bash
grep -n "sidequest" docs/frontend-integration.ru.md
```
Expected: two matches around lines 55 and 62.

- [ ] **Step 2: Replace `sidequest` with `bonus` on both lines**

For each match, edit the file so that:
- ``` `main` или `sidequest` ``` becomes ``` `main` или `bonus` ```
- ``` 'main' | 'sidequest' ``` becomes ``` 'main' | 'bonus' ```

- [ ] **Step 3: Verify**

Run: `grep -n "sidequest" docs/frontend-integration.ru.md`
Expected: no matches.

- [ ] **Step 4: Commit**

```bash
git add docs/frontend-integration.ru.md
git commit -m "docs: rename sidequest -> bonus in frontend integration"
```

Return to `InsurancePlatformPy/`.

---

## Phase 12 — docker-compose + final smoke

### Task 12.1: Add MinIO to docker-compose

**Files:** Modify `docker-compose.yml`

- [ ] **Step 1: Read the existing compose file**

Run: `cat docker-compose.yml`

- [ ] **Step 2: Append a `minio` service and `minio_data` volume**

Add under `services:` (preserving existing services):

```yaml
  minio:
    image: minio/minio:latest
    container_name: minio
    ports:
      - "9000:9000"
      - "9001:9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ACCESS_KEY:-minioadmin}
      MINIO_ROOT_PASSWORD: ${MINIO_SECRET_KEY:-minioadmin}
    command: server /data --console-address ":9001"
    volumes:
      - minio_data:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 10s
      timeout: 5s
      retries: 5
```

And under `volumes:` (append, don't remove existing):

```yaml
  minio_data:
```

- [ ] **Step 3: Bring it up and confirm**

```bash
docker compose up -d minio
docker compose ps minio
```
Expected: state `healthy` (after a few seconds).

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "compose: add MinIO service"
```

### Task 12.2: End-to-end smoke checklist (manual)

This step is not automated. Add a small README block.

- [ ] **Step 1: Append a smoke-test recipe to `README.md`**

Read the file, then append:

```markdown
## Chat smoke test (manual)

```bash
# 1. Infra
docker compose up -d database minio

# 2. DB
DB_NAME=insurance_platform uv run alembic upgrade head

# 3. App
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

# 4. (In another terminal) Seed a support agent
curl -u admin:admin -X POST http://localhost:8000/api/v1/admin/support-agents/ \
  -H 'Content-Type: application/json' \
  -d '{"login":"alice","password":"changeme","display_name":"Alice"}'

# 5. (In another terminal) Bring up the Go gateway
cd ../InsurancePlatform
INTERNAL_SECRET="dev-internal-secret-change-me" \
PYTHON_BASE_URL=http://localhost:8000 \
go run ./cmd/chatgw

# 6. Use the existing test harness frontend to:
#    - register a customer, get the JWT
#    - open the customer WS to ws://localhost:8080/ws?type=main with the JWT subprotocol
#    - support-login on the new endpoint, get the JWT
#    - GET /api/v1/support/chats/ to learn the chat_id
#    - open the support WS to ws://localhost:8080/ws?type=main&chat_id=<id>
#    - send a message from each side; both tabs should see fan-out
#    - upload a file via POST /api/v1/files/ (form-data: file, chat_id)
#    - send_file via WS with the returned file_id
```

(The exact env var names in the Go process may differ — check `cmd/chatgw/main.go` for current names.)
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: chat smoke-test recipe"
```

---

## Verification gate

Before declaring complete:

- [ ] **All Python unit tests pass**

```bash
uv run pytest tests/unit -q
```
Expected: all green.

- [ ] **All Python integration tests pass**

```bash
DB_NAME=insurance_platform_test uv run alembic upgrade head
uv run pytest tests/integration -q
```
Expected: all green.

- [ ] **All Go tests pass**

```bash
cd ../InsurancePlatform
go build ./...
go test ./... -race -count=1 -timeout 60s
```
Expected: all green.

- [ ] **Manual smoke (per Task 12.2)** completes end-to-end: customer ↔ support text message exchange + file send in both `main` and `bonus` chats.

---

## Out of scope (per spec)

- MIME allowlist on uploads.
- Range requests on file download.
- File / message garbage collection.
- Support refresh tokens.
- Multi-instance Go gateway / Redis pub/sub.
- Rate limiting.
- Hardening the hard-coded `localhost:6379` Redis URL in `app/main.py`.
- Reconciling the two `User` model definitions in the Python codebase.
- Structured JSON logging with `request_id` / `subject` / `chat_id` /
  `message_id` correlation. The spec mentions this but the existing project
  has no logging convention set up. Use Python's default `logging` for now;
  proper structured logging is a follow-up.
