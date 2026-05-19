# Chat Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Python (FastAPI) server side that the Go `chatgw` WebSocket gateway depends on — internal endpoints, chat/message/file data model, support login, MinIO presigned uploads, public chat endpoints.

**Architecture:** Additive Python work on `InsurancePlatformPy`. New routers (`internal`, `files`, `support_auth`), new tables (`chats`, `messages`, `chat_files`), MinIO via aioboto3, Alembic bootstrap, support of two roles (`user` SMS, `support` password). Existing auth flow untouched except a `role` claim on the JWT and one call from `register()` to seed each user's two chats. Spec: `docs/superpowers/specs/2026-05-19-chat-integration-design.md`.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 async + asyncpg, Pydantic v2, Alembic, aioboto3 → MinIO/S3, pytest + pytest-asyncio + httpx ASGI transport, Postgres 18.

---

## File Structure

### Phase 0 — Bootstrap
- Create: `pyproject.toml` *(modify)* — add `alembic`, `aioboto3`, `python-multipart`, dev deps
- Create: `pytest.ini`
- Create: `tests/conftest.py`
- Create: `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`, `tests/migrations/__init__.py`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/0001_baseline.py`
- Create: `docker-compose.yml` *(modify)* — add `minio` + `minio-init` services
- Create: `.env.example`
- Modify: `app/core/config.py` — new settings

### Phase 1 — Schema & data model
- Modify: `app/models/base.py` — add `uuid_pk`
- Modify: `app/models/tables/user.py` — add `role`, `login`
- Create: `app/models/tables/chat.py`
- Create: `app/models/tables/message.py`
- Create: `app/models/tables/chat_file.py`
- Create: `alembic/versions/0002_add_role_login_to_users.py`
- Create: `alembic/versions/0003_chat_domain.py`
- Create: `tests/migrations/test_chat_domain_migration.py`

### Phase 2 — Auth changes
- Modify: `app/services/auth_service.py` — promote helpers, add role to JWT
- Create: `app/services/internal_token_service.py`
- Create: `app/services/support_auth_service.py`
- Create: `app/api/dependencies/__init__.py`
- Create: `app/api/dependencies/internal_secret.py`
- Create: `app/api/routers/support_auth.py`
- Create: `tests/unit/test_internal_token_service.py`
- Create: `tests/unit/test_support_auth_service.py`
- Create: `tests/integration/test_support_auth_endpoints.py`

### Phase 3 — Chat core
- Create: `app/models/dto/chat.py`
- Create: `app/models/dto/internal.py`
- Create: `app/repositories/chat_repository.py`
- Create: `app/repositories/message_repository.py`
- Create: `app/services/chat_service.py`
- Modify: `app/services/auth_service.py` — call `ChatService.ensure_user_chats`
- Create: `tests/unit/test_chat_service.py`

### Phase 4 — Internal endpoints
- Create: `app/api/routers/internal.py`
- Modify: `app/main.py` — `include_router(internal_router)`
- Create: `tests/integration/test_internal_ws_validate.py`
- Create: `tests/integration/test_internal_messages.py`

### Phase 5 — Files
- Modify: `app/core/config.py` *(additional)* — verify MinIO settings
- Create: `app/core/minio.py`
- Create: `app/repositories/file_repository.py`
- Create: `app/services/file_service.py`
- Create: `app/api/routers/files.py`
- Modify: `app/api/main_router.py` — include `files_router`
- Modify: `app/services/chat_service.py` — extend `persist_message` for kind="file"
- Modify: `app/main.py` — MinIO bucket bootstrap in `lifespan`
- Create: `tests/unit/test_file_service.py`
- Create: `tests/integration/test_files_endpoints.py`

### Phase 6 — Public chat endpoints
- Modify: `app/api/routers/chats.py` — implement four bodies, leave two stubbed
- Create: `tests/integration/test_chats_endpoints.py`

### Phase 7 — Support seeder
- Create: `app/scripts/__init__.py`
- Create: `app/scripts/create_support_user.py`

### Phase 8 — Final wiring & docs
- Modify: `app/api/main_router.py` *(if not already)* — include `support_auth_router`
- Create: `tests/README.md`

---

## Phase 0: Bootstrap

Goal: dependencies installed, test infrastructure ready, Alembic working, MinIO running, no app changes yet.

### Task 0.1: Add dependencies to pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Edit pyproject.toml**

Append to the `dependencies` list and add a `[dependency-groups]` section. Final file content:

```toml
[project]
name = "insuranceplatformpy"
version = "0.1.0"
description = "Add your description here"
readme = "README.md"
requires-python = ">=3.13"
dependencies = [
    "fastapi>=0.110.0",
    "uvicorn>=0.27.0",
    "sqlalchemy[asyncio]>=2.0.0",
    "asyncpg>=0.29.0",
    "psycopg2-binary>=2.9.0",
    "pydantic-settings>=2.0.0",
    "passlib[bcrypt]>=1.7.0",
    "email-validator>=2.1.0",
    "python-jose[cryptography]>=3.3.0",
    "requests>=2.34.2",
    "httpx>=0.28.1",
    "redis>=7.4.0",
    "alembic>=1.13.0",
    "aioboto3>=12.0.0",
    "python-multipart>=0.0.9",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "freezegun>=1.4",
]
```

- [ ] **Step 2: Sync dependencies**

Run: `uv sync`
Expected: lockfile updated; no errors.

- [ ] **Step 3: Verify imports work**

Run: `uv run python -c "import alembic; import aioboto3; import pytest; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "add alembic, aioboto3, pytest deps"
```

### Task 0.2: Add config settings

**Files:**
- Modify: `app/core/config.py`

- [ ] **Step 1: Replace `Settings` class body**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "insurance_platform"
    db_user: str = "postgres"
    db_password: str = "postgres"

    jwt_secret_key: str = "your-secret-key-change-in-production-min-32-chars"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30

    referral_accrual_delay_days: int = 15
    referral_link_base_url: str = "https://example.com/r/"

    # Internal-secret for /internal/* endpoints
    internal_secret: str = ""

    # MinIO / S3
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "chat-files"
    minio_use_ssl: bool = False
    minio_presign_put_expires_seconds: int = 600
    minio_presign_get_expires_seconds: int = 7 * 24 * 3600

    # Chat / file limits
    file_max_size_bytes: int = 25 * 1024 * 1024
    file_mime_allowlist: list[str] = []
    message_max_body_bytes: int = 32768

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


settings = Settings()
```

- [ ] **Step 2: Verify settings parse**

Run: `uv run python -c "from app.core.config import settings; print(settings.minio_bucket, settings.message_max_body_bytes)"`
Expected: `chat-files 32768`

- [ ] **Step 3: Commit**

```bash
git add app/core/config.py
git commit -m "add minio, internal-secret, file/message limit settings"
```

### Task 0.3: Update docker-compose with MinIO

**Files:**
- Modify: `docker-compose.yml`
- Create: `.env.example`

- [ ] **Step 1: Add MinIO services to docker-compose.yml**

Append the `minio` and `minio-init` services under `services:`, and add `minio_data` to the `volumes:` section. Final file:

```yaml
networks:
    net:
        driver: bridge

services:
    alembic:
        container_name: alembic
        networks:
            - net
        build: .
        command: uv run alembic upgrade head
        depends_on:
            database:
                condition: service_healthy
        environment:
            DATABASE_URL: postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}

    app:
        networks:
            - net
        build: .
        container_name: app
        restart: unless-stopped
        ports:
            - "8000:8000"
        depends_on:
            database:
                condition: service_healthy
            minio:
                condition: service_healthy
        env_file:
            - .env

    database:
        networks:
            - net
        image: postgres:18
        container_name: database
        restart: unless-stopped
        env_file:
            - .env
        ports:
            - "5432:5432"
        volumes:
            - "postgres_data:/var/lib/postgresql/data"
        healthcheck:
            test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
            interval: 10s
            timeout: 5s
            retries: 10
        logging:
            driver: "json-file"
            options:
                max-size: "5m"
                max-file: "5"

    redis:
        networks:
            - net
        image: redis:8
        env_file:
            - .env
        container_name: redis
        command: ["redis-server", "--requirepass", "${REDIS_PASSWORD}"]
        ports:
            - "6379:6379"
        healthcheck:
            test: ["CMD", "redis-cli", "ping"]
            interval: 10s
            timeout: 5s
            retries: 5
            start_period: 10s
        logging:
            driver: "json-file"
            options:
                max-size: "5m"
                max-file: "5"
        restart: unless-stopped
        volumes:
            - redis_data:/data

    minio:
        image: minio/minio:latest
        container_name: minio
        networks:
            - net
        env_file:
            - .env
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
        networks:
            - net
        depends_on:
            minio:
                condition: service_healthy
        env_file:
            - .env
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

- [ ] **Step 2: Create .env.example**

```bash
# Postgres
POSTGRES_HOST=database
POSTGRES_PORT=5432
POSTGRES_DB=insurance_platform
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
DB_HOST=database
DB_PORT=5432
DB_NAME=insurance_platform
DB_USER=postgres
DB_PASSWORD=postgres

# Redis
REDIS_PASSWORD=redispass

# JWT
JWT_SECRET_KEY=replace-me-with-32+-chars-of-random
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=15
JWT_REFRESH_TOKEN_EXPIRE_DAYS=30

# chatgw integration
INTERNAL_SECRET=replace-me-with-long-random-string

# MinIO (server side)
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=replace-me-with-long-random-string
MINIO_BUCKET=chat-files

# MinIO (app side)
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=replace-me-with-long-random-string
MINIO_USE_SSL=false
```

- [ ] **Step 3: Start MinIO and verify it's healthy**

```bash
docker compose up -d minio minio-init
docker compose ps minio          # expect "healthy"
docker compose logs minio-init   # expect "Bucket created successfully `local/chat-files`"
```

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "add minio + minio-init services"
```

### Task 0.4: Bootstrap Alembic

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/0001_baseline.py`

- [ ] **Step 1: Create alembic.ini at repo root**

```ini
[alembic]
script_location = alembic
prepend_sys_path = .
version_path_separator = os
sqlalchemy.url = postgresql+psycopg2://postgres:postgres@localhost:5432/insurance_platform

[post_write_hooks]

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

Note: `sqlalchemy.url` is overridden at runtime by `env.py` from the `DATABASE_URL` env var.

- [ ] **Step 2: Create alembic/env.py**

```python
import asyncio
import importlib
import os
import pkgutil
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.models.base import Base
import app.models.tables as tables_pkg

# Import every module in app.models.tables so all models register on Base.metadata.
for _, module_name, _ in pkgutil.iter_modules(tables_pkg.__path__):
    importlib.import_module(f"app.models.tables.{module_name}")

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

db_url = os.environ.get("DATABASE_URL")
if db_url:
    # Force async driver for runtime; alembic ini uses sync URL.
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgresql+psycopg2://"):
        db_url = db_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    config.set_main_option("sqlalchemy.url", db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
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

- [ ] **Step 3: Create alembic/script.py.mako**

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 4: Create alembic/versions/0001_baseline.py**

```python
"""baseline

Revision ID: 0001_baseline
Revises:
Create Date: 2026-05-19

Creates users and refresh_tokens tables if they don't already exist (idempotent
guard for devs whose DB was created via SQLAlchemy create_all).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if not _table_exists("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("phone", sa.String(length=20), nullable=False, unique=True),
            sa.Column("password_hash", sa.String(length=255), nullable=False),
            sa.Column("first_name", sa.String(length=100), nullable=True),
            sa.Column("last_name", sa.String(length=100), nullable=True),
            sa.Column("patronymic", sa.String(length=100), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        )

    if not _table_exists("refresh_tokens"):
        op.create_table(
            "refresh_tokens",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("token", sa.String(length=500), nullable=False, unique=True, index=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    op.drop_table("refresh_tokens")
    op.drop_table("users")
```

Note: if your existing `users` table has additional columns (e.g., `referral_code`) created by SQLAlchemy `create_all`, the baseline migration won't reproduce them — but it doesn't need to, since the guard `_table_exists` skips recreation entirely. Alembic just stamps `0001_baseline` as the current revision.

- [ ] **Step 5: Run baseline migration**

```bash
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/insurance_platform uv run alembic upgrade head
```

Expected: `Running upgrade  -> 0001_baseline, baseline`. Run `uv run alembic current` to confirm.

- [ ] **Step 6: Commit**

```bash
git add alembic.ini alembic/
git commit -m "bootstrap alembic with idempotent baseline"
```

### Task 0.5: Set up test infrastructure

**Files:**
- Create: `pytest.ini`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/migrations/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create pytest.ini**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -ra --strict-markers --tb=short
markers =
    integration: tests that require Postgres + MinIO running
```

- [ ] **Step 2: Create empty `__init__.py` files**

```bash
mkdir -p tests/unit tests/integration tests/migrations
touch tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py tests/migrations/__init__.py
```

- [ ] **Step 3: Create tests/conftest.py**

```python
"""Shared test fixtures.

Strategy:
- One test DB and one test bucket, created/migrated once per session.
- Each test runs inside a savepoint that is rolled back at the end.
- HTTP client is an httpx.AsyncClient with ASGITransport (no Uvicorn boot).
"""
import asyncio
import os
import subprocess
from typing import AsyncGenerator

import aioboto3
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.database import get_async_session
from app.main import app

TEST_DB_NAME = f"{settings.db_name}_test"
TEST_BUCKET = f"{settings.minio_bucket}-test"


def _test_database_url(driver: str = "asyncpg") -> str:
    return (
        f"postgresql+{driver}://{settings.db_user}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_port}/{TEST_DB_NAME}"
    )


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
def _ensure_test_db_and_migrate():
    """Drop+recreate the test DB and run all migrations before the test session."""
    import psycopg2
    from psycopg2 import sql

    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        dbname="postgres",
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s"),
            [TEST_DB_NAME],
        )
        cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(TEST_DB_NAME)))
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB_NAME)))
    conn.close()

    env = os.environ.copy()
    env["DATABASE_URL"] = _test_database_url(driver="psycopg2")
    subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True, env=env)
    yield


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(_test_database_url(), echo=False, future=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Per-test session with savepoint rollback."""
    async with test_engine.connect() as conn:
        trans = await conn.begin()
        AsyncSessionLocal = async_sessionmaker(bind=conn, class_=AsyncSession, expire_on_commit=False)
        async with AsyncSessionLocal() as session:
            nested = await session.begin_nested()
            try:
                yield session
            finally:
                if nested.is_active:
                    await nested.rollback()
        await trans.rollback()


@pytest_asyncio.fixture
async def client(db_session) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_session():
        yield db_session
    app.dependency_overrides[get_async_session] = override_get_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="session")
async def _minio_session():
    yield aioboto3.Session()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _ensure_test_bucket(_minio_session):
    """Create the test bucket once per session; do not delete (cheaper)."""
    async with _minio_session.client(
        "s3",
        endpoint_url=f"http://{settings.minio_endpoint}",
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        region_name="us-east-1",
    ) as s3:
        try:
            await s3.create_bucket(Bucket=TEST_BUCKET)
        except s3.exceptions.BucketAlreadyOwnedByYou:
            pass
        except s3.exceptions.BucketAlreadyExists:
            pass
    # Patch settings.minio_bucket for the test session
    settings.minio_bucket = TEST_BUCKET
    yield


@pytest_asyncio.fixture
async def s3_client(_minio_session):
    async with _minio_session.client(
        "s3",
        endpoint_url=f"http://{settings.minio_endpoint}",
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        region_name="us-east-1",
    ) as s3:
        yield s3
```

- [ ] **Step 4: Add a sanity test**

Create `tests/unit/test_smoke.py`:

```python
def test_pytest_runs():
    assert 1 + 1 == 2
```

- [ ] **Step 5: Run the smoke test**

Run: `uv run pytest tests/unit/test_smoke.py -v`
Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add pytest.ini tests/
git commit -m "test infra: pytest, conftest, savepoint isolation, asgi client"
```

---

## Phase 1: Schema & data model

Goal: all new tables exist, `users` has `role` and `login`, every existing user has both chats backfilled.

### Task 1.1: Add `uuid_pk` annotation to base.py

**Files:**
- Modify: `app/models/base.py`

- [ ] **Step 1: Append `uuid_pk` annotation**

Final `app/models/base.py`:

```python
import uuid
from datetime import datetime
from typing import Annotated

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Common type annotations
int_pk = Annotated[int, mapped_column(primary_key=True, autoincrement=True)]
uuid_pk = Annotated[
    uuid.UUID,
    mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
]
created_at = Annotated[
    datetime,
    mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False),
]
updated_at = Annotated[
    datetime,
    mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    ),
]


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


class TimestampMixin:
    """Mixin to add created_at and updated_at columns."""

    created_at: Mapped[created_at]
    updated_at: Mapped[updated_at]
```

- [ ] **Step 2: Verify import**

Run: `uv run python -c "from app.models.base import uuid_pk; print(uuid_pk)"`
Expected: prints the Annotated type without error.

- [ ] **Step 3: Commit**

```bash
git add app/models/base.py
git commit -m "add uuid_pk annotation for chat domain models"
```

### Task 1.2: Add `role` and `login` columns to users

**Files:**
- Modify: `app/models/tables/user.py`
- Create: `alembic/versions/0002_add_role_login_to_users.py`

- [ ] **Step 1: Update User model**

Final `app/models/tables/user.py`:

```python
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String

from app.models.base import Base, int_pk, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int_pk]
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    patronymic: Mapped[str | None] = mapped_column(String(100), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, server_default="user")
    login: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
```

- [ ] **Step 2: Create the migration**

`alembic/versions/0002_add_role_login_to_users.py`:

```python
"""add role and login to users

Revision ID: 0002_add_role_login_to_users
Revises: 0001_baseline
Create Date: 2026-05-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_add_role_login_to_users"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=20), nullable=False, server_default="user"),
    )
    op.add_column(
        "users",
        sa.Column("login", sa.String(length=64), nullable=True),
    )
    op.create_unique_constraint("uq_users_login", "users", ["login"])


def downgrade() -> None:
    op.drop_constraint("uq_users_login", "users", type_="unique")
    op.drop_column("users", "login")
    op.drop_column("users", "role")
```

- [ ] **Step 3: Run the migration**

```bash
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/insurance_platform uv run alembic upgrade head
```

Expected: `Running upgrade 0001_baseline -> 0002_add_role_login_to_users, add role and login to users`.

- [ ] **Step 4: Verify columns**

```bash
docker compose exec database psql -U postgres -d insurance_platform -c "\d users"
```

Expected: output includes `role` (varchar(20) NOT NULL DEFAULT 'user') and `login` (varchar(64), UNIQUE).

- [ ] **Step 5: Commit**

```bash
git add app/models/tables/user.py alembic/versions/0002_add_role_login_to_users.py
git commit -m "add role and login columns to users"
```

### Task 1.3: Create Chat model

**Files:**
- Create: `app/models/tables/chat.py`

- [ ] **Step 1: Write the model**

```python
import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class Chat(Base, TimestampMixin):
    __tablename__ = "chats"

    id: Mapped[uuid_pk]
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(20), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "type", name="uq_chats_user_type"),
    )
```

- [ ] **Step 2: Verify import (no runtime DB yet)**

Run: `uv run python -c "from app.models.tables.chat import Chat; print(Chat.__tablename__)"`
Expected: `chats`

- [ ] **Step 3: Commit**

```bash
git add app/models/tables/chat.py
git commit -m "add Chat model"
```

### Task 1.4: Create Message model

**Files:**
- Create: `app/models/tables/message.py`

- [ ] **Step 1: Write the model**

```python
from sqlalchemy import ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, uuid_pk


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid_pk]
    chat_id: Mapped["uuid.UUID"] = mapped_column(  # type: ignore[name-defined]
        PG_UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_id: Mapped["uuid.UUID | None"] = mapped_column(  # type: ignore[name-defined]
        PG_UUID(as_uuid=True), ForeignKey("chat_files.id"), nullable=True
    )
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

- [ ] **Step 2: Verify import**

Run: `uv run python -c "from app.models.tables.message import Message; print(Message.__tablename__)"`
Expected: `messages`

- [ ] **Step 3: Commit**

```bash
git add app/models/tables/message.py
git commit -m "add Message model"
```

### Task 1.5: Create ChatFile model

**Files:**
- Create: `app/models/tables/chat_file.py`

- [ ] **Step 1: Write the model**

```python
from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class ChatFile(Base, TimestampMixin):
    __tablename__ = "chat_files"

    id: Mapped[uuid_pk]
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    chat_id: Mapped["uuid.UUID"] = mapped_column(  # type: ignore[name-defined]
        PG_UUID(as_uuid=True), ForeignKey("chats.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime: Mapped[str] = mapped_column(String(127), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )
    object_key: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (
        Index("ix_chat_files_user_status", "user_id", "status"),
    )
```

- [ ] **Step 2: Verify import**

Run: `uv run python -c "from app.models.tables.chat_file import ChatFile; print(ChatFile.__tablename__)"`
Expected: `chat_files`

- [ ] **Step 3: Commit**

```bash
git add app/models/tables/chat_file.py
git commit -m "add ChatFile model"
```

### Task 1.6: Chat domain migration with backfill

**Files:**
- Create: `alembic/versions/0003_chat_domain.py`

- [ ] **Step 1: Write the migration**

```python
"""chat domain

Revision ID: 0003_chat_domain
Revises: 0002_add_role_login_to_users
Create Date: 2026-05-19

Creates chats, messages, chat_files plus a data migration that backfills the
two chats (main + sidequest) for every existing user. Requires pgcrypto for
gen_random_uuid() in the backfill.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0003_chat_domain"
down_revision: Union[str, None] = "0002_add_role_login_to_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")

    op.create_table(
        "chats",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "type", name="uq_chats_user_type"),
    )

    op.create_table(
        "chat_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chats.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("mime", sa.String(length=127), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("object_key", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chat_files_user_status", "chat_files", ["user_id", "status"])

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chat_files.id"), nullable=True),
        sa.Column("client_msg_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_messages_chat_created", "messages", ["chat_id", "created_at"])
    op.execute(
        """
        CREATE UNIQUE INDEX uq_messages_chat_client_msg_id
        ON messages (chat_id, client_msg_id)
        WHERE client_msg_id IS NOT NULL;
        """
    )

    # Data backfill: create both chats for every existing user.
    op.execute(
        """
        INSERT INTO chats (id, user_id, type, created_at, updated_at)
        SELECT gen_random_uuid(), u.id, t.type, now(), now()
        FROM users u CROSS JOIN (VALUES ('main'), ('sidequest')) AS t(type)
        ON CONFLICT (user_id, type) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_messages_chat_created", table_name="messages")
    op.execute("DROP INDEX IF EXISTS uq_messages_chat_client_msg_id;")
    op.drop_table("messages")
    op.drop_index("ix_chat_files_user_status", table_name="chat_files")
    op.drop_table("chat_files")
    op.drop_table("chats")
```

- [ ] **Step 2: Run the migration**

```bash
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/insurance_platform uv run alembic upgrade head
```

Expected: `Running upgrade 0002_add_role_login_to_users -> 0003_chat_domain, chat domain`.

- [ ] **Step 3: Verify tables and backfill**

```bash
docker compose exec database psql -U postgres -d insurance_platform -c "\dt"
docker compose exec database psql -U postgres -d insurance_platform -c "SELECT (SELECT count(*) FROM users) AS users, (SELECT count(*) FROM chats) AS chats;"
```

Expected: `chats` count = `users` count × 2.

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/0003_chat_domain.py
git commit -m "chat domain migration with two-chat backfill"
```

### Task 1.7: Migration test

**Files:**
- Create: `tests/migrations/test_chat_domain_migration.py`

- [ ] **Step 1: Write the test**

```python
"""Verifies the 0003 migration backfills both chats per existing user."""
import os
import subprocess

import psycopg2
import pytest
from psycopg2 import sql

from app.core.config import settings

MIG_TEST_DB = f"{settings.db_name}_migration_test"


def _admin_conn():
    return psycopg2.connect(
        host=settings.db_host, port=settings.db_port,
        user=settings.db_user, password=settings.db_password,
        dbname="postgres",
    )


def _recreate_db():
    conn = _admin_conn()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s"),
            [MIG_TEST_DB],
        )
        cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(MIG_TEST_DB)))
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(MIG_TEST_DB)))
    conn.close()


def _upgrade_to(revision: str):
    env = os.environ.copy()
    env["DATABASE_URL"] = (
        f"postgresql+psycopg2://{settings.db_user}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_port}/{MIG_TEST_DB}"
    )
    subprocess.run(["uv", "run", "alembic", "upgrade", revision], check=True, env=env)


@pytest.mark.integration
def test_backfill_creates_two_chats_per_existing_user():
    _recreate_db()

    # Migrate up to 0002 (users table exists, no chats yet).
    _upgrade_to("0002_add_role_login_to_users")

    # Insert pre-existing users.
    conn = psycopg2.connect(
        host=settings.db_host, port=settings.db_port,
        user=settings.db_user, password=settings.db_password,
        dbname=MIG_TEST_DB,
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        for i in range(3):
            cur.execute(
                "INSERT INTO users (email, phone, password_hash) VALUES (%s, %s, %s)",
                (f"u{i}@x.com", f"+1000000000{i}", "x"),
            )

    # Run 0003 (chat domain + backfill).
    _upgrade_to("0003_chat_domain")

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM chats;")
        chat_count = cur.fetchone()[0]
        cur.execute("SELECT count(DISTINCT type) FROM chats;")
        distinct_types = cur.fetchone()[0]
    conn.close()

    assert chat_count == 6, f"expected 3 users * 2 types = 6, got {chat_count}"
    assert distinct_types == 2, f"expected both 'main' and 'sidequest', got {distinct_types}"
```

- [ ] **Step 2: Run the test**

```bash
uv run pytest tests/migrations/test_chat_domain_migration.py -v -m integration
```

Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/migrations/test_chat_domain_migration.py
git commit -m "test migration backfills two chats per existing user"
```

---

## Phase 2: Auth changes

Goal: JWTs carry `role`, internal token service decodes them, support agents can log in with login+password.

### Task 2.1: Promote access-token and refresh-token helpers to module-level

**Files:**
- Modify: `app/services/auth_service.py`

- [ ] **Step 1: Read current file**

Read `app/services/auth_service.py` so the diff is clear before editing.

- [ ] **Step 2: Add module-level functions; class methods become passthroughs**

Insert these module-level functions near the top of `auth_service.py` (after imports, before `class AuthService`):

```python
def make_access_token(user_id: int, role: str = "user") -> str:
    """Issue a JWT access token carrying user_id and role.

    Role is read by /internal/auth/ws-validate. Tokens issued before this
    function existed lack the role claim; consumers default to "user".
    """
    payload = {
        "user_id": user_id,
        "role": role,
        "type": "access",
        "exp": datetime.utcnow() + timedelta(minutes=settings.jwt_access_token_expire_minutes),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


async def create_refresh_token(session, user_id: int) -> "RefreshToken":
    """Insert a new opaque refresh token for the given user."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(days=settings.jwt_refresh_token_expire_days)
    refresh_token = RefreshToken(
        token=token,
        user_id=user_id,
        expires_at=expires_at,
    )
    session.add(refresh_token)
    await session.commit()
    await session.refresh(refresh_token)
    return refresh_token
```

Replace the class methods so they delegate to the module-level versions. Find:

```python
    def _generate_access_token(self, user_id: int) -> str:
        payload = {
            "user_id": user_id,
            "type": "access",
            "exp": datetime.utcnow() + timedelta(minutes=settings.jwt_access_token_expire_minutes),
            "iat": datetime.utcnow(),
        }
        return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
```

Replace with:

```python
    def _generate_access_token(self, user_id: int, role: str = "user") -> str:
        return make_access_token(user_id, role)
```

Find:

```python
    async def _create_refresh_token(self, user_id: int) -> RefreshToken:
        token = self._generate_refresh_token()
        expires_at = datetime.utcnow() + timedelta(days=settings.jwt_refresh_token_expire_days)

        refresh_token = RefreshToken(
            token=token,
            user_id=user_id,
            expires_at=expires_at,
        )

        self._session.add(refresh_token)
        await self._session.commit()
        await self._session.refresh(refresh_token)

        return refresh_token
```

Replace with:

```python
    async def _create_refresh_token(self, user_id: int) -> RefreshToken:
        return await create_refresh_token(self._session, user_id)
```

Update each call site of `self._generate_access_token(user.id)` inside `AuthService` to pass `user.role`:

```python
access_token = self._generate_access_token(user.id, user.role)
```

There are three such call sites — in `register`, `login`, and `refresh`. Change all three.

- [ ] **Step 3: Verify existing flows still pass syntax check**

Run: `uv run python -c "from app.services.auth_service import AuthService, make_access_token, create_refresh_token; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/services/auth_service.py
git commit -m "promote token helpers to module-level, add role claim to JWT"
```

### Task 2.2: Internal token service

**Files:**
- Create: `app/services/internal_token_service.py`
- Create: `tests/unit/test_internal_token_service.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_internal_token_service.py`:

```python
from datetime import datetime, timedelta

import pytest
from jose import jwt as jose_jwt

from app.core.config import settings
from app.services.internal_token_service import (
    DecodedToken,
    InvalidToken,
    decode_access_token,
)


def _encode(payload: dict) -> str:
    return jose_jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def test_decode_valid_token_with_role():
    token = _encode({
        "user_id": 42,
        "role": "support",
        "type": "access",
        "exp": datetime.utcnow() + timedelta(minutes=5),
    })
    result = decode_access_token(token)
    assert result == DecodedToken(user_id=42, role="support")


def test_decode_token_without_role_defaults_to_user():
    token = _encode({
        "user_id": 7,
        "type": "access",
        "exp": datetime.utcnow() + timedelta(minutes=5),
    })
    result = decode_access_token(token)
    assert result == DecodedToken(user_id=7, role="user")


def test_decode_expired_token_raises():
    token = _encode({
        "user_id": 1,
        "role": "user",
        "type": "access",
        "exp": datetime.utcnow() - timedelta(minutes=1),
    })
    with pytest.raises(InvalidToken):
        decode_access_token(token)


def test_decode_tampered_signature_raises():
    token = _encode({"user_id": 1, "role": "user", "type": "access",
                     "exp": datetime.utcnow() + timedelta(minutes=5)})
    tampered = token[:-2] + "AA"
    with pytest.raises(InvalidToken):
        decode_access_token(tampered)
```

- [ ] **Step 2: Run test, expect failure**

Run: `uv run pytest tests/unit/test_internal_token_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.internal_token_service'`.

- [ ] **Step 3: Write implementation**

`app/services/internal_token_service.py`:

```python
from dataclasses import dataclass

from jose import JWTError, jwt

from app.core.config import settings


class InvalidToken(Exception):
    """Raised when a JWT cannot be decoded or is otherwise invalid."""


@dataclass(frozen=True)
class DecodedToken:
    user_id: int
    role: str  # "user" | "support"


def decode_access_token(token: str) -> DecodedToken:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as e:
        raise InvalidToken(str(e)) from e

    if payload.get("type") != "access":
        raise InvalidToken("not an access token")

    user_id = payload.get("user_id")
    if not isinstance(user_id, int):
        raise InvalidToken("missing or invalid user_id")

    role = payload.get("role", "user")
    if role not in ("user", "support"):
        raise InvalidToken(f"invalid role: {role!r}")

    return DecodedToken(user_id=user_id, role=role)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `uv run pytest tests/unit/test_internal_token_service.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/internal_token_service.py tests/unit/test_internal_token_service.py
git commit -m "internal token service: decode JWT, default role=user"
```

### Task 2.3: Internal-secret dependency

**Files:**
- Create: `app/api/dependencies/__init__.py`
- Create: `app/api/dependencies/internal_secret.py`

- [ ] **Step 1: Create empty package init**

```bash
mkdir -p app/api/dependencies
touch app/api/dependencies/__init__.py
```

- [ ] **Step 2: Write the dependency**

`app/api/dependencies/internal_secret.py`:

```python
"""Router-level dependency: requires X-Internal-Secret header to match
settings.internal_secret. Mounted on the /internal/* router.

A configured-but-empty value is treated as a 500 (server misconfiguration),
not a silent allow-all.
"""
import secrets

from fastapi import Header, HTTPException, status

from app.core.config import settings

INTERNAL_SECRET_HEADER = "X-Internal-Secret"


async def require_internal_secret(
    x_internal_secret: str = Header(default="", alias=INTERNAL_SECRET_HEADER),
) -> None:
    expected = settings.internal_secret
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="internal secret not configured",
        )
    if not secrets.compare_digest(x_internal_secret, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
```

- [ ] **Step 3: Verify import**

Run: `uv run python -c "from app.api.dependencies.internal_secret import require_internal_secret, INTERNAL_SECRET_HEADER; print(INTERNAL_SECRET_HEADER)"`
Expected: `X-Internal-Secret`

- [ ] **Step 4: Commit**

```bash
git add app/api/dependencies/
git commit -m "X-Internal-Secret dependency"
```

### Task 2.4: SupportAuthService

**Files:**
- Create: `app/services/support_auth_service.py`
- Create: `tests/unit/test_support_auth_service.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_support_auth_service.py`:

```python
import pytest
from passlib.context import CryptContext
from sqlalchemy import select

from app.models.tables.user import User
from app.services.support_auth_service import SupportAuthService

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def _make_support(session, login="alice", password="pw"):
    user = User(
        email=f"{login}@x.com",
        phone=f"+10000{hash(login) % 100000:05d}",
        password_hash=pwd_context.hash(password),
        role="support",
        login=login,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_customer(session, login="bob", password="pw"):
    user = User(
        email=f"{login}@x.com",
        phone=f"+10001{hash(login) % 100000:05d}",
        password_hash=pwd_context.hash(password),
        role="user",
        login=None,
    )
    session.add(user)
    await session.flush()
    return user


@pytest.mark.integration
async def test_support_login_success(db_session):
    await _make_support(db_session, login="alice", password="goodpw")
    svc = SupportAuthService(db_session)
    result = await svc.login("alice", "goodpw")
    assert result.access_token
    assert result.refresh_token
    assert result.user.role == "support"


@pytest.mark.integration
async def test_support_login_wrong_password(db_session):
    await _make_support(db_session, login="alice", password="goodpw")
    svc = SupportAuthService(db_session)
    with pytest.raises(ValueError, match="Invalid credentials"):
        await svc.login("alice", "wrongpw")


@pytest.mark.integration
async def test_support_login_unknown_login(db_session):
    svc = SupportAuthService(db_session)
    with pytest.raises(ValueError, match="Invalid credentials"):
        await svc.login("nobody", "pw")


@pytest.mark.integration
async def test_support_login_rejects_customer_role(db_session):
    await _make_customer(db_session, login="bob", password="pw")
    svc = SupportAuthService(db_session)
    with pytest.raises(ValueError, match="Invalid credentials"):
        # Customer should not be able to log in via support endpoint even with right password.
        await svc.login("bob", "pw")
```

- [ ] **Step 2: Run test, expect failure**

Run: `uv run pytest tests/unit/test_support_auth_service.py -v -m integration`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Check Pydantic DTOs for TokenResponse shape**

Read `app/models/users/dto/__init__.py` or wherever `TokenResponse` is defined. The new service must return that exact type. Quick check:

```bash
grep -rn "class TokenResponse" app/
```

Use the result to import `TokenResponse` correctly in step 4.

- [ ] **Step 4: Write the service**

`app/services/support_auth_service.py`:

```python
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables.user import User
from app.models.users.dto import TokenResponse, UserResponse
from app.services.auth_service import create_refresh_token, make_access_token

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class SupportAuthService:
    """Login + password auth for support-role users.

    Refresh / logout reuse the existing /api/v1/auth/refresh/ and /logout/
    endpoints — refresh tokens are role-agnostic in the DB.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def login(self, login: str, password: str) -> TokenResponse:
        result = await self._session.execute(
            select(User).where(User.login == login, User.role == "support")
        )
        user = result.scalar_one_or_none()
        if not user or not pwd_context.verify(password, user.password_hash):
            raise ValueError("Invalid credentials")

        access = make_access_token(user.id, user.role)
        refresh = await create_refresh_token(self._session, user.id)

        return TokenResponse(
            access_token=access,
            refresh_token=refresh.token,
            user=UserResponse.model_validate(user),
        )
```

If `TokenResponse` or `UserResponse` are defined elsewhere, adjust the import.

- [ ] **Step 5: Run tests, expect pass**

Run: `uv run pytest tests/unit/test_support_auth_service.py -v -m integration`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add app/services/support_auth_service.py tests/unit/test_support_auth_service.py
git commit -m "SupportAuthService: login+password for support role"
```

### Task 2.5: Support login router

**Files:**
- Create: `app/api/routers/support_auth.py`
- Modify: `app/api/main_router.py`
- Create: `tests/integration/test_support_auth_endpoints.py`

- [ ] **Step 1: Write the failing endpoint test**

`tests/integration/test_support_auth_endpoints.py`:

```python
import pytest
from jose import jwt as jose_jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.models.tables.user import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def _make_support(session, login, password):
    user = User(
        email=f"{login}@x.com",
        phone=f"+10000{hash(login) % 100000:05d}",
        password_hash=pwd_context.hash(password),
        role="support",
        login=login,
    )
    session.add(user)
    await session.flush()
    return user


@pytest.mark.integration
async def test_support_login_returns_role_support_token(db_session, client):
    await _make_support(db_session, "alice", "goodpw")
    await db_session.commit()  # commit so the endpoint sees the row

    resp = await client.post("/api/v1/auth/support/login/", json={"login": "alice", "password": "goodpw"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    access = body["access_token"]
    payload = jose_jwt.decode(access, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    assert payload["role"] == "support"
    assert payload["user_id"] > 0


@pytest.mark.integration
async def test_support_login_wrong_password_returns_400(db_session, client):
    await _make_support(db_session, "alice", "goodpw")
    await db_session.commit()
    resp = await client.post("/api/v1/auth/support/login/", json={"login": "alice", "password": "x"})
    assert resp.status_code == 400
    assert "Invalid credentials" in resp.json()["detail"]
```

Note: `await db_session.commit()` in these tests is needed only when the endpoint uses a different session than the test fixture; if the fixture's session is correctly injected via `dependency_overrides`, the endpoint sees the in-savepoint rows already. If the override isn't in place, commits would persist across tests — which the savepoint pattern still rolls back at the outer transaction.

- [ ] **Step 2: Run test, expect failure**

Run: `uv run pytest tests/integration/test_support_auth_endpoints.py -v -m integration`
Expected: FAIL — endpoint not found (`404` or import error).

- [ ] **Step 3: Write the router**

`app/api/routers/support_auth.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.models.users.dto import TokenResponse
from app.services.support_auth_service import SupportAuthService


class SupportLoginRequest(BaseModel):
    login: str
    password: str


router = APIRouter(prefix="/auth/support", tags=["auth"])


@router.post("/login/", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def support_login(
    data: SupportLoginRequest,
    session: AsyncSession = Depends(get_async_session),
) -> TokenResponse:
    svc = SupportAuthService(session)
    try:
        return await svc.login(data.login, data.password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
```

- [ ] **Step 4: Wire it into the api_router**

Edit `app/api/main_router.py`:

```python
from fastapi import APIRouter

from app.api.routers.applications import router as applications_router
from app.api.routers.auth import router as auth_router
from app.api.routers.bonuses import router as bonuses_router
from app.api.routers.certificates import router as certificates_router
from app.api.routers.chats import router as chats_router
from app.api.routers.deals import router as deals_router
from app.api.routers.files import router as files_router
from app.api.routers.me import router as me_router
from app.api.routers.partners import router as partners_router
from app.api.routers.referrals import router as referrals_router
from app.api.routers.reports import router as reports_router
from app.api.routers.support_auth import router as support_auth_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(support_auth_router)
api_router.include_router(me_router)
api_router.include_router(referrals_router)
api_router.include_router(partners_router)
api_router.include_router(applications_router)
api_router.include_router(deals_router)
api_router.include_router(bonuses_router)
api_router.include_router(certificates_router)
api_router.include_router(chats_router)
api_router.include_router(files_router)
api_router.include_router(reports_router)
```

Note: this imports `files_router` which doesn't exist yet (Task 5.4 creates it). Temporarily comment that import + include line until Task 5.4 ships, OR create an empty `app/api/routers/files.py` with `router = APIRouter(prefix="/files", tags=["files"])` placeholder.

Choose the placeholder approach to avoid import errors at this checkpoint:

```bash
cat > app/api/routers/files.py <<'EOF'
from fastapi import APIRouter

router = APIRouter(prefix="/files", tags=["files"])
EOF
```

- [ ] **Step 5: Run tests, expect pass**

Run: `uv run pytest tests/integration/test_support_auth_endpoints.py -v -m integration`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add app/api/routers/support_auth.py app/api/routers/files.py app/api/main_router.py tests/integration/test_support_auth_endpoints.py
git commit -m "support login endpoint with role=support JWT claim"
```

---

## Phase 3: Chat core

Goal: chat service can ensure-create both chats for a user, resolve chat_id for ws-validate, persist text messages with idempotency.

### Task 3.1: Internal DTOs

**Files:**
- Create: `app/models/dto/internal.py`
- Create: `app/models/dto/chat.py`

- [ ] **Step 1: Write internal-endpoint DTOs**

`app/models/dto/internal.py`:

```python
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

ChatType = Literal["main", "sidequest"]
Role = Literal["user", "support"]
Kind = Literal["message", "file"]


class WsValidateRequest(BaseModel):
    token: str
    chat_type: ChatType
    chat_id_hint: str = ""


class WsValidateResponse(BaseModel):
    user_id: str           # stringified to match Go's string ID type
    role: Role
    chat_id: str


class FileMetaResponse(BaseModel):
    file_id: UUID
    name: str
    mime: str
    size: int
    url: str


class InternalMessageRequest(BaseModel):
    user_id: str           # accept as string, parsed to int
    role: Role
    kind: Kind
    body: str | None = None
    file_id: UUID | None = None
    client_msg_id: str | None = None


class CanonicalMessage(BaseModel):
    """Matches Go's message.Message JSON shape exactly."""
    id: UUID
    chat_id: UUID
    user_id: str
    role: Role
    kind: Kind
    body: str = ""
    file: FileMetaResponse | None = None
    client_msg_id: str = ""
    created_at: datetime
```

- [ ] **Step 2: Write chat DTOs**

`app/models/dto/chat.py`:

```python
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class CounterpartInfo(BaseModel):
    user_id: int
    display_name: str
    role: Literal["user", "support"]


class MessagePreview(BaseModel):
    kind: Literal["message", "file"]
    body_preview: str | None = None
    file_name: str | None = None
    created_at: datetime


class ChatListItem(BaseModel):
    id: UUID
    type: Literal["main", "sidequest"]
    counterpart: CounterpartInfo
    last_message: MessagePreview | None = None
    last_activity_at: datetime | None = None
    unread_count: int = 0


class MessageHistoryItem(BaseModel):
    id: UUID
    chat_id: UUID
    user_id: int
    role: Literal["user", "support"]
    kind: Literal["message", "file"]
    body: str | None = None
    file: "FileMetaResponse | None" = None
    client_msg_id: str | None = None
    created_at: datetime


class FileMetaResponse(BaseModel):
    file_id: UUID
    name: str
    mime: str
    size: int
    url: str


class FilePresignRequest(BaseModel):
    chat_id: UUID
    name: str
    mime: str
    size: int


class FilePresignResponse(BaseModel):
    file_id: UUID
    upload_url: str
    upload_method: Literal["PUT"] = "PUT"
    upload_headers: dict[str, str] = {}
    expires_at: datetime


MessageHistoryItem.model_rebuild()
```

- [ ] **Step 3: Verify imports**

Run: `uv run python -c "from app.models.dto.internal import WsValidateRequest; from app.models.dto.chat import ChatListItem; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/models/dto/internal.py app/models/dto/chat.py
git commit -m "chat and internal DTOs"
```

### Task 3.2: Chat and message repositories

**Files:**
- Create: `app/repositories/chat_repository.py`
- Create: `app/repositories/message_repository.py`

- [ ] **Step 1: Write chat repository**

`app/repositories/chat_repository.py`:

```python
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables.chat import Chat


class ChatRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_user_chat(self, user_id: int, chat_type: str) -> Chat | None:
        result = await self._session.execute(
            select(Chat).where(Chat.user_id == user_id, Chat.type == chat_type)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, chat_id: UUID) -> Chat | None:
        result = await self._session.execute(select(Chat).where(Chat.id == chat_id))
        return result.scalar_one_or_none()

    async def ensure_user_chats(self, user_id: int) -> None:
        """Idempotent: insert main + sidequest if missing. Uses UPSERT to
        survive the race where two callers try to create concurrently."""
        stmt = pg_insert(Chat).values([
            {"user_id": user_id, "type": "main"},
            {"user_id": user_id, "type": "sidequest"},
        ]).on_conflict_do_nothing(index_elements=["user_id", "type"])
        await self._session.execute(stmt)

    async def list_chats_for_user(self, user_id: int) -> list[Chat]:
        result = await self._session.execute(
            select(Chat).where(Chat.user_id == user_id).order_by(Chat.type)
        )
        return list(result.scalars().all())
```

- [ ] **Step 2: Write message repository**

`app/repositories/message_repository.py`:

```python
from datetime import datetime
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables.message import Message


class MessageRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_client_msg_id(self, chat_id: UUID, client_msg_id: str) -> Message | None:
        result = await self._session.execute(
            select(Message).where(
                Message.chat_id == chat_id, Message.client_msg_id == client_msg_id
            )
        )
        return result.scalar_one_or_none()

    async def insert(self, **fields) -> Message:
        msg = Message(**fields)
        self._session.add(msg)
        await self._session.flush()
        return msg

    async def list_history(
        self,
        chat_id: UUID,
        limit: int = 50,
        before_created_at: datetime | None = None,
    ) -> list[Message]:
        stmt = select(Message).where(Message.chat_id == chat_id)
        if before_created_at is not None:
            stmt = stmt.where(Message.created_at < before_created_at)
        stmt = stmt.order_by(desc(Message.created_at)).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def latest_for_chat(self, chat_id: UUID) -> Message | None:
        result = await self._session.execute(
            select(Message).where(Message.chat_id == chat_id)
            .order_by(desc(Message.created_at)).limit(1)
        )
        return result.scalar_one_or_none()
```

- [ ] **Step 3: Verify imports**

Run: `uv run python -c "from app.repositories.chat_repository import ChatRepository; from app.repositories.message_repository import MessageRepository; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/repositories/chat_repository.py app/repositories/message_repository.py
git commit -m "chat + message repositories"
```

### Task 3.3: ChatService — ensure_user_chats and resolve_chat_id

**Files:**
- Create: `app/services/chat_service.py`
- Create: `tests/unit/test_chat_service.py`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_chat_service.py`:

```python
from uuid import UUID

import pytest
from passlib.context import CryptContext
from sqlalchemy import select

from app.models.tables.chat import Chat
from app.models.tables.user import User
from app.services.chat_service import ChatResolutionError, ChatService

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def _make_user(session, role="user"):
    user = User(
        email="u@x.com", phone=f"+1000{hash(role) % 1000000:06d}",
        password_hash="x", role=role,
    )
    session.add(user)
    await session.flush()
    return user


@pytest.mark.integration
async def test_ensure_user_chats_inserts_both_types(db_session):
    user = await _make_user(db_session)
    svc = ChatService(db_session)
    await svc.ensure_user_chats(user.id)

    result = await db_session.execute(select(Chat).where(Chat.user_id == user.id))
    chats = list(result.scalars().all())
    assert {c.type for c in chats} == {"main", "sidequest"}


@pytest.mark.integration
async def test_ensure_user_chats_idempotent(db_session):
    user = await _make_user(db_session)
    svc = ChatService(db_session)
    await svc.ensure_user_chats(user.id)
    await svc.ensure_user_chats(user.id)  # second call must not raise or duplicate

    result = await db_session.execute(select(Chat).where(Chat.user_id == user.id))
    chats = list(result.scalars().all())
    assert len(chats) == 2


@pytest.mark.integration
async def test_resolve_chat_id_for_user_returns_own_chat(db_session):
    user = await _make_user(db_session)
    svc = ChatService(db_session)
    await svc.ensure_user_chats(user.id)

    chat_id = await svc.resolve_chat_id(user_id=user.id, role="user", chat_type="main", chat_id_hint="")
    assert isinstance(chat_id, UUID)


@pytest.mark.integration
async def test_resolve_chat_id_for_support_requires_hint(db_session):
    support = await _make_user(db_session, role="support")
    svc = ChatService(db_session)
    with pytest.raises(ChatResolutionError, match="chat_id_hint required"):
        await svc.resolve_chat_id(user_id=support.id, role="support", chat_type="main", chat_id_hint="")


@pytest.mark.integration
async def test_resolve_chat_id_for_support_validates_type(db_session):
    user = await _make_user(db_session, role="user")
    support = await _make_user(db_session, role="support")
    svc = ChatService(db_session)
    await svc.ensure_user_chats(user.id)
    main_chat = (await db_session.execute(
        select(Chat).where(Chat.user_id == user.id, Chat.type == "main")
    )).scalar_one()

    # Wrong type — main_chat is of type "main", but support requests "sidequest".
    with pytest.raises(ChatResolutionError, match="chat type mismatch"):
        await svc.resolve_chat_id(
            user_id=support.id, role="support",
            chat_type="sidequest", chat_id_hint=str(main_chat.id),
        )


@pytest.mark.integration
async def test_resolve_chat_id_user_missing_chat_raises(db_session):
    user = await _make_user(db_session)
    svc = ChatService(db_session)
    # Did NOT call ensure_user_chats — simulate the "should never happen" case.
    with pytest.raises(ChatResolutionError, match="chat not found"):
        await svc.resolve_chat_id(user_id=user.id, role="user", chat_type="main", chat_id_hint="")
```

- [ ] **Step 2: Run tests, expect failure**

Run: `uv run pytest tests/unit/test_chat_service.py -v -m integration`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write the service**

`app/services/chat_service.py`:

```python
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.chat_repository import ChatRepository

CHAT_TYPES = ("main", "sidequest")
ROLES = ("user", "support")
KINDS = ("message", "file")
INTERNAL_SECRET_HEADER = "X-Internal-Secret"


class ChatResolutionError(Exception):
    """Raised when ws-validate cannot resolve a chat_id."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class ChatService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._chats = ChatRepository(session)

    async def ensure_user_chats(self, user_id: int) -> None:
        await self._chats.ensure_user_chats(user_id)

    async def resolve_chat_id(
        self,
        *,
        user_id: int,
        role: str,
        chat_type: str,
        chat_id_hint: str,
    ) -> UUID:
        if chat_type not in CHAT_TYPES:
            raise ChatResolutionError(f"invalid chat_type: {chat_type!r}", status_code=400)

        if role == "user":
            chat = await self._chats.get_user_chat(user_id, chat_type)
            if chat is None:
                raise ChatResolutionError("chat not found", status_code=404)
            return chat.id

        if role == "support":
            if not chat_id_hint:
                raise ChatResolutionError("chat_id_hint required for support role", status_code=400)
            try:
                hint_uuid = UUID(chat_id_hint)
            except ValueError:
                raise ChatResolutionError("chat_id_hint not a valid UUID", status_code=400)
            chat = await self._chats.get_by_id(hint_uuid)
            if chat is None:
                raise ChatResolutionError("chat not found", status_code=400)
            if chat.type != chat_type:
                raise ChatResolutionError("chat type mismatch", status_code=400)
            return chat.id

        raise ChatResolutionError(f"invalid role: {role!r}", status_code=400)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `uv run pytest tests/unit/test_chat_service.py -v -m integration`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/chat_service.py tests/unit/test_chat_service.py
git commit -m "ChatService: ensure_user_chats + resolve_chat_id"
```

### Task 3.4: Wire ensure_user_chats into AuthService.register

**Files:**
- Modify: `app/services/auth_service.py`

- [ ] **Step 1: Add the call to register()**

Find the `register` method in `app/services/auth_service.py`. After the user row is inserted and flushed (but before `self._session.commit()`), insert a call to `ChatService.ensure_user_chats(user.id)`. Pattern:

```python
# At the top of auth_service.py, alongside other imports:
from app.services.chat_service import ChatService

# Inside register(), after user is created and flushed:
await ChatService(self._session).ensure_user_chats(user.id)
```

The exact location depends on the current shape of `register()`; insert the call between user creation and the final `commit()` so both writes happen in one transaction.

- [ ] **Step 2: Write an integration test**

Append to `tests/integration/test_support_auth_endpoints.py` (or create `tests/integration/test_registration_seeds_chats.py`):

```python
import pytest
from sqlalchemy import select

from app.models.tables.chat import Chat


@pytest.mark.integration
async def test_register_seeds_both_chats(client, db_session):
    payload = {
        "phone": "+19998887777",
        "code": "0000",                       # adjust if your mock SMS uses a different code
        "email": "newuser@x.com",
        "first_name": "New",
        "last_name": "User",
        "password": "pw",
    }
    resp = await client.post("/api/v1/auth/register/", json=payload)
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]
    assert token

    # Inspect the DB directly. Find the user we just created.
    from app.models.tables.user import User
    user = (await db_session.execute(
        select(User).where(User.phone == "+19998887777")
    )).scalar_one()

    chats = (await db_session.execute(
        select(Chat).where(Chat.user_id == user.id)
    )).scalars().all()
    types = {c.type for c in chats}
    assert types == {"main", "sidequest"}
```

Adjust the `code` value to match `MOCK_SMS_CODE` in `AuthService` (check by `grep MOCK_SMS_CODE app/services/auth_service.py`). Also prepend a call to `request-code` if needed.

- [ ] **Step 3: Run test, expect pass**

Run: `uv run pytest tests/integration/test_registration_seeds_chats.py -v -m integration`
Expected: 1 passed.

- [ ] **Step 4: Commit**

```bash
git add app/services/auth_service.py tests/integration/test_registration_seeds_chats.py
git commit -m "register() now seeds main + sidequest chats"
```

### Task 3.5: ChatService.persist_message (text only first)

**Files:**
- Modify: `app/services/chat_service.py`
- Modify: `tests/unit/test_chat_service.py`

- [ ] **Step 1: Write failing tests for persist_message (text)**

Append to `tests/unit/test_chat_service.py`:

```python
import pytest as _pytest
from sqlalchemy import select as _select

from app.models.tables.message import Message
from app.services.chat_service import MessagePersistError


@_pytest.mark.integration
async def test_persist_message_text_inserts_row(db_session):
    user = await _make_user(db_session)
    svc = ChatService(db_session)
    await svc.ensure_user_chats(user.id)
    chat_id = await svc.resolve_chat_id(user_id=user.id, role="user", chat_type="main", chat_id_hint="")

    msg = await svc.persist_message(
        chat_id=chat_id, sender_user_id=user.id, role="user",
        kind="message", body="hello", file_id=None, client_msg_id="cm-1",
    )
    assert msg.body == "hello"
    assert msg.kind == "message"
    assert msg.client_msg_id == "cm-1"


@_pytest.mark.integration
async def test_persist_message_dedup_returns_existing(db_session):
    user = await _make_user(db_session)
    svc = ChatService(db_session)
    await svc.ensure_user_chats(user.id)
    chat_id = await svc.resolve_chat_id(user_id=user.id, role="user", chat_type="main", chat_id_hint="")

    first = await svc.persist_message(
        chat_id=chat_id, sender_user_id=user.id, role="user",
        kind="message", body="hello", file_id=None, client_msg_id="cm-1",
    )
    second = await svc.persist_message(
        chat_id=chat_id, sender_user_id=user.id, role="user",
        kind="message", body="DIFFERENT", file_id=None, client_msg_id="cm-1",
    )
    assert second.id == first.id
    assert second.body == "hello"     # original, not updated


@_pytest.mark.integration
async def test_persist_message_empty_body_raises(db_session):
    user = await _make_user(db_session)
    svc = ChatService(db_session)
    await svc.ensure_user_chats(user.id)
    chat_id = await svc.resolve_chat_id(user_id=user.id, role="user", chat_type="main", chat_id_hint="")

    with _pytest.raises(MessagePersistError, match="body required"):
        await svc.persist_message(
            chat_id=chat_id, sender_user_id=user.id, role="user",
            kind="message", body="", file_id=None, client_msg_id=None,
        )


@_pytest.mark.integration
async def test_persist_message_oversize_body_raises(db_session):
    from app.core.config import settings
    user = await _make_user(db_session)
    svc = ChatService(db_session)
    await svc.ensure_user_chats(user.id)
    chat_id = await svc.resolve_chat_id(user_id=user.id, role="user", chat_type="main", chat_id_hint="")

    big = "x" * (settings.message_max_body_bytes + 1)
    with _pytest.raises(MessagePersistError, match="too large"):
        await svc.persist_message(
            chat_id=chat_id, sender_user_id=user.id, role="user",
            kind="message", body=big, file_id=None, client_msg_id=None,
        )
```

- [ ] **Step 2: Run tests, expect failure**

Run: `uv run pytest tests/unit/test_chat_service.py -v -m integration -k persist`
Expected: FAIL — `MessagePersistError` not defined.

- [ ] **Step 3: Extend ChatService**

Append to `app/services/chat_service.py`:

```python
from app.core.config import settings as _settings
from app.models.tables.message import Message
from app.repositories.message_repository import MessageRepository


class MessagePersistError(Exception):
    """Raised when a message cannot be persisted (validation failure)."""

    def __init__(self, message: str, status_code: int = 400, code: str = "validation"):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


# Add inside ChatService:
async def persist_message(
    self,
    *,
    chat_id,
    sender_user_id: int,
    role: str,
    kind: str,
    body: str | None,
    file_id,
    client_msg_id: str | None,
) -> Message:
    if role not in ROLES:
        raise MessagePersistError(f"invalid role: {role!r}")
    if kind not in KINDS:
        raise MessagePersistError(f"invalid kind: {kind!r}")

    if client_msg_id:
        existing = await MessageRepository(self._session).get_by_client_msg_id(chat_id, client_msg_id)
        if existing is not None:
            return existing

    if kind == "message":
        if not body or not body.strip():
            raise MessagePersistError("body required for kind=message")
        if len(body.encode("utf-8")) > _settings.message_max_body_bytes:
            raise MessagePersistError("body too large", status_code=413, code="payload_too_large")
    else:
        # kind == "file" — full validation lives in Phase 5 (file_service integration);
        # for now reject so the test suite catches premature use.
        raise MessagePersistError("file messages not yet supported")

    msg = await MessageRepository(self._session).insert(
        chat_id=chat_id,
        user_id=sender_user_id,
        role=role,
        kind=kind,
        body=body,
        file_id=None,
        client_msg_id=client_msg_id,
    )
    await self._session.flush()
    return msg
```

Place the `MessagePersistError` class and the `persist_message` method inside the existing `ChatService` class — the snippet shows it as a class-level method.

- [ ] **Step 4: Run tests, expect pass**

Run: `uv run pytest tests/unit/test_chat_service.py -v -m integration -k persist`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/chat_service.py tests/unit/test_chat_service.py
git commit -m "ChatService.persist_message: text with idempotency and validation"
```

---

## Phase 4: Internal endpoints

Goal: Go can call `POST /internal/auth/ws-validate` and `POST /internal/chats/{chat_id}/messages` and get correct responses including idempotent retries.

### Task 4.1: Internal router with ws-validate

**Files:**
- Create: `app/api/routers/internal.py`
- Modify: `app/main.py`
- Create: `tests/integration/test_internal_ws_validate.py`

- [ ] **Step 1: Write the failing test**

`tests/integration/test_internal_ws_validate.py`:

```python
from datetime import datetime, timedelta

import pytest
from jose import jwt as jose_jwt
from passlib.context import CryptContext
from sqlalchemy import select

from app.core.config import settings
from app.models.tables.chat import Chat
from app.models.tables.user import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
HEADERS = {"X-Internal-Secret": "test-secret"}


def _encode(user_id: int, role: str = "user", minutes_valid: int = 5) -> str:
    return jose_jwt.encode(
        {
            "user_id": user_id, "role": role, "type": "access",
            "exp": datetime.utcnow() + timedelta(minutes=minutes_valid),
        },
        settings.jwt_secret_key, algorithm=settings.jwt_algorithm,
    )


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    monkeypatch.setattr(settings, "internal_secret", "test-secret")


async def _make_user_with_chats(db_session, role="user"):
    user = User(
        email="x@x.com", phone=f"+1000{hash(role + datetime.utcnow().isoformat()) % 1000000:06d}",
        password_hash="x", role=role,
    )
    db_session.add(user)
    await db_session.flush()
    from app.services.chat_service import ChatService
    await ChatService(db_session).ensure_user_chats(user.id)
    await db_session.flush()
    return user


@pytest.mark.integration
async def test_ws_validate_missing_secret_returns_403(client):
    resp = await client.post(
        "/internal/auth/ws-validate",
        json={"token": "x", "chat_type": "main", "chat_id_hint": ""},
    )
    assert resp.status_code == 403


@pytest.mark.integration
async def test_ws_validate_bad_token_returns_401(client):
    resp = await client.post(
        "/internal/auth/ws-validate",
        json={"token": "not-a-jwt", "chat_type": "main", "chat_id_hint": ""},
        headers=HEADERS,
    )
    assert resp.status_code == 401


@pytest.mark.integration
async def test_ws_validate_user_resolves_main_chat(db_session, client):
    user = await _make_user_with_chats(db_session)
    await db_session.commit()
    token = _encode(user.id, role="user")
    resp = await client.post(
        "/internal/auth/ws-validate",
        json={"token": token, "chat_type": "main", "chat_id_hint": ""},
        headers=HEADERS,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user_id"] == str(user.id)
    assert body["role"] == "user"
    main_chat_id = (await db_session.execute(
        select(Chat.id).where(Chat.user_id == user.id, Chat.type == "main")
    )).scalar_one()
    assert body["chat_id"] == str(main_chat_id)


@pytest.mark.integration
async def test_ws_validate_support_requires_chat_id_hint(db_session, client):
    support = await _make_user_with_chats(db_session, role="support")
    await db_session.commit()
    token = _encode(support.id, role="support")
    resp = await client.post(
        "/internal/auth/ws-validate",
        json={"token": token, "chat_type": "main", "chat_id_hint": ""},
        headers=HEADERS,
    )
    assert resp.status_code == 400


@pytest.mark.integration
async def test_ws_validate_support_wrong_chat_type_returns_400(db_session, client):
    user = await _make_user_with_chats(db_session)
    support = await _make_user_with_chats(db_session, role="support")
    await db_session.commit()

    main_chat_id = (await db_session.execute(
        select(Chat.id).where(Chat.user_id == user.id, Chat.type == "main")
    )).scalar_one()
    token = _encode(support.id, role="support")
    resp = await client.post(
        "/internal/auth/ws-validate",
        json={"token": token, "chat_type": "sidequest", "chat_id_hint": str(main_chat_id)},
        headers=HEADERS,
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: Run tests, expect failure**

Run: `uv run pytest tests/integration/test_internal_ws_validate.py -v -m integration`
Expected: FAIL — endpoint missing.

- [ ] **Step 3: Write the router**

`app/api/routers/internal.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.internal_secret import require_internal_secret
from app.core.database import get_async_session
from app.models.dto.internal import WsValidateRequest, WsValidateResponse
from app.services.chat_service import ChatResolutionError, ChatService
from app.services.internal_token_service import InvalidToken, decode_access_token

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(require_internal_secret)])


@router.post("/auth/ws-validate", response_model=WsValidateResponse)
async def ws_validate(
    data: WsValidateRequest,
    session: AsyncSession = Depends(get_async_session),
) -> WsValidateResponse:
    try:
        decoded = decode_access_token(data.token)
    except InvalidToken as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    svc = ChatService(session)
    try:
        chat_id = await svc.resolve_chat_id(
            user_id=decoded.user_id,
            role=decoded.role,
            chat_type=data.chat_type,
            chat_id_hint=data.chat_id_hint,
        )
    except ChatResolutionError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    return WsValidateResponse(
        user_id=str(decoded.user_id),
        role=decoded.role,
        chat_id=str(chat_id),
    )
```

- [ ] **Step 4: Mount the internal router in main.py**

Edit `app/main.py`:

```python
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI

from app.api.main_router import api_router
from app.api.routers.internal import router as internal_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = redis.Redis(
        host="localhost",
        port=6379,
        decode_responses=True,
    )
    yield
    await app.state.redis.close()


app = FastAPI(
    title="Insurance Platform API",
    description="API for Insurance Platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(api_router)
app.include_router(internal_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
```

- [ ] **Step 5: Run tests, expect pass**

Run: `uv run pytest tests/integration/test_internal_ws_validate.py -v -m integration`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add app/api/routers/internal.py app/main.py tests/integration/test_internal_ws_validate.py
git commit -m "POST /internal/auth/ws-validate"
```

### Task 4.2: Internal POST /chats/{chat_id}/messages (text)

**Files:**
- Modify: `app/api/routers/internal.py`
- Create: `tests/integration/test_internal_messages.py`

- [ ] **Step 1: Write the failing tests**

`tests/integration/test_internal_messages.py`:

```python
from datetime import datetime
from uuid import UUID

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.tables.chat import Chat
from app.models.tables.message import Message
from app.models.tables.user import User
from app.services.chat_service import ChatService

HEADERS = {"X-Internal-Secret": "test-secret"}


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    monkeypatch.setattr(settings, "internal_secret", "test-secret")


async def _make_user_with_chats(db_session):
    user = User(email="x@x.com", phone=f"+1{datetime.utcnow().timestamp()}", password_hash="x", role="user")
    db_session.add(user)
    await db_session.flush()
    await ChatService(db_session).ensure_user_chats(user.id)
    await db_session.flush()
    return user


async def _get_main_chat_id(db_session, user_id: int) -> UUID:
    return (await db_session.execute(
        select(Chat.id).where(Chat.user_id == user_id, Chat.type == "main")
    )).scalar_one()


@pytest.mark.integration
async def test_post_text_message_inserts_row(db_session, client):
    user = await _make_user_with_chats(db_session)
    chat_id = await _get_main_chat_id(db_session, user.id)
    await db_session.commit()

    resp = await client.post(
        f"/internal/chats/{chat_id}/messages",
        json={
            "user_id": str(user.id), "role": "user", "kind": "message",
            "body": "hello world", "client_msg_id": "cm-1",
        },
        headers=HEADERS,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["body"] == "hello world"
    assert body["kind"] == "message"
    assert body["chat_id"] == str(chat_id)
    assert body["user_id"] == str(user.id)
    assert body["client_msg_id"] == "cm-1"


@pytest.mark.integration
async def test_idempotent_retry_returns_same_message(db_session, client):
    user = await _make_user_with_chats(db_session)
    chat_id = await _get_main_chat_id(db_session, user.id)
    await db_session.commit()

    payload = {
        "user_id": str(user.id), "role": "user", "kind": "message",
        "body": "hello", "client_msg_id": "dup-key",
    }
    first = (await client.post(f"/internal/chats/{chat_id}/messages", json=payload, headers=HEADERS)).json()
    second_payload = {**payload, "body": "DIFFERENT"}
    second = (await client.post(f"/internal/chats/{chat_id}/messages", json=second_payload, headers=HEADERS)).json()

    assert first["id"] == second["id"]
    assert second["body"] == "hello"   # original, not updated


@pytest.mark.integration
async def test_empty_body_returns_400(db_session, client):
    user = await _make_user_with_chats(db_session)
    chat_id = await _get_main_chat_id(db_session, user.id)
    await db_session.commit()

    resp = await client.post(
        f"/internal/chats/{chat_id}/messages",
        json={"user_id": str(user.id), "role": "user", "kind": "message", "body": ""},
        headers=HEADERS,
    )
    assert resp.status_code == 400


@pytest.mark.integration
async def test_oversize_body_returns_413(db_session, client, monkeypatch):
    monkeypatch.setattr(settings, "message_max_body_bytes", 10)
    user = await _make_user_with_chats(db_session)
    chat_id = await _get_main_chat_id(db_session, user.id)
    await db_session.commit()

    resp = await client.post(
        f"/internal/chats/{chat_id}/messages",
        json={"user_id": str(user.id), "role": "user", "kind": "message", "body": "way too long for the limit"},
        headers=HEADERS,
    )
    assert resp.status_code == 413


@pytest.mark.integration
async def test_chat_not_found_returns_404(client):
    fake_chat = "00000000-0000-0000-0000-000000000000"
    resp = await client.post(
        f"/internal/chats/{fake_chat}/messages",
        json={"user_id": "1", "role": "user", "kind": "message", "body": "x"},
        headers=HEADERS,
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests, expect failure**

Run: `uv run pytest tests/integration/test_internal_messages.py -v -m integration`
Expected: FAIL — route not found.

- [ ] **Step 3: Extend the internal router**

Append to `app/api/routers/internal.py`:

```python
from uuid import UUID

from app.models.dto.internal import CanonicalMessage, InternalMessageRequest
from app.repositories.chat_repository import ChatRepository
from app.services.chat_service import MessagePersistError


@router.post("/chats/{chat_id}/messages", response_model=CanonicalMessage)
async def post_internal_message(
    chat_id: UUID,
    data: InternalMessageRequest,
    session: AsyncSession = Depends(get_async_session),
) -> CanonicalMessage:
    chat = await ChatRepository(session).get_by_id(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")

    try:
        sender_user_id = int(data.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid user_id")

    svc = ChatService(session)
    try:
        msg = await svc.persist_message(
            chat_id=chat_id,
            sender_user_id=sender_user_id,
            role=data.role,
            kind=data.kind,
            body=data.body,
            file_id=data.file_id,
            client_msg_id=data.client_msg_id,
        )
    except MessagePersistError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    await session.commit()

    return CanonicalMessage(
        id=msg.id,
        chat_id=msg.chat_id,
        user_id=str(msg.user_id),
        role=msg.role,
        kind=msg.kind,
        body=msg.body or "",
        file=None,
        client_msg_id=msg.client_msg_id or "",
        created_at=msg.created_at,
    )
```

- [ ] **Step 4: Run tests, expect pass**

Run: `uv run pytest tests/integration/test_internal_messages.py -v -m integration`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add app/api/routers/internal.py tests/integration/test_internal_messages.py
git commit -m "POST /internal/chats/{chat_id}/messages for text"
```

---

## Phase 5: Files

Goal: clients can presign-upload directly to MinIO, confirm, and send file messages through Go.

### Task 5.1: MinIO client + bucket bootstrap on startup

**Files:**
- Create: `app/core/minio.py`
- Modify: `app/main.py`

- [ ] **Step 1: Write the MinIO client factory**

`app/core/minio.py`:

```python
import aioboto3

from app.core.config import settings

_session: aioboto3.Session | None = None


def _get_session() -> aioboto3.Session:
    global _session
    if _session is None:
        _session = aioboto3.Session()
    return _session


def s3_client():
    """Returns an async-context-manager that yields an S3 client."""
    return _get_session().client(
        "s3",
        endpoint_url=f"{'https' if settings.minio_use_ssl else 'http'}://{settings.minio_endpoint}",
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
        region_name="us-east-1",
    )


async def ensure_bucket_exists() -> None:
    """Idempotently create the configured bucket on startup."""
    async with s3_client() as s3:
        try:
            await s3.head_bucket(Bucket=settings.minio_bucket)
        except Exception:
            await s3.create_bucket(Bucket=settings.minio_bucket)
```

- [ ] **Step 2: Extend lifespan in main.py**

Replace the lifespan in `app/main.py`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = redis.Redis(
        host="localhost",
        port=6379,
        decode_responses=True,
    )
    from app.core.minio import ensure_bucket_exists
    await ensure_bucket_exists()
    yield
    await app.state.redis.close()
```

- [ ] **Step 3: Smoke test by booting the app**

Run (against the docker-compose MinIO):

```bash
uv run python -c "import asyncio; from app.core.minio import ensure_bucket_exists; asyncio.run(ensure_bucket_exists()); print('OK')"
```

Expected: `OK`. If MinIO isn't reachable, `docker compose up -d minio minio-init` first.

- [ ] **Step 4: Commit**

```bash
git add app/core/minio.py app/main.py
git commit -m "MinIO client factory + bucket bootstrap on app startup"
```

### Task 5.2: File repository

**Files:**
- Create: `app/repositories/file_repository.py`

- [ ] **Step 1: Write the repository**

`app/repositories/file_repository.py`:

```python
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables.chat_file import ChatFile


class FileRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def insert(self, **fields) -> ChatFile:
        f = ChatFile(**fields)
        self._session.add(f)
        await self._session.flush()
        return f

    async def get_by_id(self, file_id: UUID) -> ChatFile | None:
        result = await self._session.execute(select(ChatFile).where(ChatFile.id == file_id))
        return result.scalar_one_or_none()

    async def list_for_chat(self, chat_id: UUID, statuses: tuple[str, ...] = ("uploaded", "linked")) -> list[ChatFile]:
        result = await self._session.execute(
            select(ChatFile).where(ChatFile.chat_id == chat_id, ChatFile.status.in_(statuses))
        )
        return list(result.scalars().all())
```

- [ ] **Step 2: Verify import**

Run: `uv run python -c "from app.repositories.file_repository import FileRepository; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/repositories/file_repository.py
git commit -m "file repository"
```

### Task 5.3: FileService — presign + confirm

**Files:**
- Create: `app/services/file_service.py`
- Create: `tests/unit/test_file_service.py`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_file_service.py`:

```python
import io
import uuid

import pytest
from sqlalchemy import select

from app.models.tables.chat import Chat
from app.models.tables.chat_file import ChatFile
from app.models.tables.user import User
from app.services.chat_service import ChatService
from app.services.file_service import FileService, FileServiceError


async def _make_user_and_chats(db_session):
    user = User(email="x@x.com", phone=f"+1{uuid.uuid4().int % 1000000000:09d}", password_hash="x", role="user")
    db_session.add(user)
    await db_session.flush()
    await ChatService(db_session).ensure_user_chats(user.id)
    await db_session.flush()
    main_chat = (await db_session.execute(
        select(Chat).where(Chat.user_id == user.id, Chat.type == "main")
    )).scalar_one()
    return user, main_chat


@pytest.mark.integration
async def test_request_upload_inserts_pending_row(db_session):
    user, chat = await _make_user_and_chats(db_session)
    svc = FileService(db_session)
    result = await svc.request_upload(
        uploader_user_id=user.id, role="user",
        chat_id=chat.id, name="hello.txt", mime="text/plain", size=11,
    )
    assert result.file_id
    assert result.upload_url.startswith("http")
    row = (await db_session.execute(select(ChatFile).where(ChatFile.id == result.file_id))).scalar_one()
    assert row.status == "pending"
    assert row.object_key.startswith(f"chats/{chat.id}/")


@pytest.mark.integration
async def test_request_upload_size_too_large(db_session, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "file_max_size_bytes", 100)
    user, chat = await _make_user_and_chats(db_session)
    svc = FileService(db_session)
    with pytest.raises(FileServiceError) as exc:
        await svc.request_upload(
            uploader_user_id=user.id, role="user",
            chat_id=chat.id, name="x", mime="text/plain", size=1000,
        )
    assert exc.value.status_code == 413


@pytest.mark.integration
async def test_confirm_upload_full_flow(db_session, s3_client):
    user, chat = await _make_user_and_chats(db_session)
    svc = FileService(db_session)
    pres = await svc.request_upload(
        uploader_user_id=user.id, role="user",
        chat_id=chat.id, name="hello.txt", mime="text/plain", size=5,
    )

    # PUT actual bytes to the presigned URL.
    import httpx
    async with httpx.AsyncClient() as ac:
        put_resp = await ac.put(pres.upload_url, content=b"hello")
        assert put_resp.status_code in (200, 201)

    # Confirm.
    confirmed = await svc.confirm_upload(file_id=pres.file_id, caller_user_id=user.id)
    assert confirmed.status == "uploaded"


@pytest.mark.integration
async def test_confirm_upload_missing_object_returns_404(db_session):
    user, chat = await _make_user_and_chats(db_session)
    svc = FileService(db_session)
    pres = await svc.request_upload(
        uploader_user_id=user.id, role="user",
        chat_id=chat.id, name="hello.txt", mime="text/plain", size=5,
    )
    # Don't upload anything, then confirm.
    with pytest.raises(FileServiceError) as exc:
        await svc.confirm_upload(file_id=pres.file_id, caller_user_id=user.id)
    assert exc.value.status_code == 404


@pytest.mark.integration
async def test_confirm_upload_size_mismatch_returns_400(db_session):
    user, chat = await _make_user_and_chats(db_session)
    svc = FileService(db_session)
    pres = await svc.request_upload(
        uploader_user_id=user.id, role="user",
        chat_id=chat.id, name="hello.txt", mime="text/plain", size=5,
    )
    # Upload MORE bytes than declared.
    import httpx
    async with httpx.AsyncClient() as ac:
        await ac.put(pres.upload_url, content=b"way more than five bytes")

    with pytest.raises(FileServiceError) as exc:
        await svc.confirm_upload(file_id=pres.file_id, caller_user_id=user.id)
    assert exc.value.status_code == 400
```

- [ ] **Step 2: Run tests, expect failure**

Run: `uv run pytest tests/unit/test_file_service.py -v -m integration`
Expected: FAIL — `FileService` not defined.

- [ ] **Step 3: Write the service**

`app/services/file_service.py`:

```python
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.minio import s3_client
from app.models.tables.chat_file import ChatFile
from app.repositories.chat_repository import ChatRepository
from app.repositories.file_repository import FileRepository


class FileServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400, code: str = "validation"):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass
class PresignResult:
    file_id: UUID
    upload_url: str
    upload_method: str
    upload_headers: dict[str, str]
    expires_at: datetime


class FileService:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._files = FileRepository(session)
        self._chats = ChatRepository(session)

    async def request_upload(
        self,
        *,
        uploader_user_id: int,
        role: str,
        chat_id: UUID,
        name: str,
        mime: str,
        size: int,
    ) -> PresignResult:
        chat = await self._chats.get_by_id(chat_id)
        if chat is None:
            raise FileServiceError("chat not found", status_code=404, code="not_found")

        # Authz: user must own the chat; any support is a participant.
        if role == "user" and chat.user_id != uploader_user_id:
            raise FileServiceError("forbidden", status_code=403, code="forbidden")
        if role not in ("user", "support"):
            raise FileServiceError("invalid role", status_code=400)

        if size > settings.file_max_size_bytes:
            raise FileServiceError("file too large", status_code=413, code="payload_too_large")
        if size <= 0:
            raise FileServiceError("size must be positive", status_code=400)

        if settings.file_mime_allowlist and mime not in settings.file_mime_allowlist:
            raise FileServiceError("mime not allowed", status_code=415, code="unsupported_type")

        file_id = uuid4()
        safe_name = name.replace("/", "_").replace("\\", "_")
        object_key = f"chats/{chat_id}/{file_id}/{safe_name}"

        await self._files.insert(
            id=file_id,
            user_id=uploader_user_id,
            chat_id=chat_id,
            name=name,
            mime=mime,
            size=size,
            status="pending",
            object_key=object_key,
        )

        async with s3_client() as s3:
            url = await s3.generate_presigned_url(
                "put_object",
                Params={"Bucket": settings.minio_bucket, "Key": object_key},
                ExpiresIn=settings.minio_presign_put_expires_seconds,
            )

        expires = datetime.now(timezone.utc) + timedelta(seconds=settings.minio_presign_put_expires_seconds)
        return PresignResult(
            file_id=file_id,
            upload_url=url,
            upload_method="PUT",
            upload_headers={},
            expires_at=expires,
        )

    async def confirm_upload(self, *, file_id: UUID, caller_user_id: int) -> ChatFile:
        row = await self._files.get_by_id(file_id)
        if row is None:
            raise FileServiceError("file not found", status_code=404, code="not_found")
        if row.user_id != caller_user_id:
            raise FileServiceError("forbidden", status_code=403, code="forbidden")
        if row.status in ("uploaded", "linked"):
            return row  # idempotent

        async with s3_client() as s3:
            try:
                head = await s3.head_object(Bucket=settings.minio_bucket, Key=row.object_key)
            except Exception as e:
                raise FileServiceError("upload not received", status_code=404, code="not_found") from e

            actual_size = int(head["ContentLength"])
            if actual_size != row.size:
                raise FileServiceError(
                    f"size mismatch: declared {row.size}, actual {actual_size}",
                    status_code=400,
                )

        row.status = "uploaded"
        await self._session.flush()
        return row

    async def make_presigned_get_url(self, object_key: str) -> str:
        async with s3_client() as s3:
            return await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.minio_bucket, "Key": object_key},
                ExpiresIn=settings.minio_presign_get_expires_seconds,
            )
```

- [ ] **Step 4: Run tests, expect pass**

Run: `uv run pytest tests/unit/test_file_service.py -v -m integration`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/file_service.py tests/unit/test_file_service.py
git commit -m "FileService: presign upload + confirm with MinIO HEAD"
```

### Task 5.4: Files router

**Files:**
- Modify: `app/api/routers/files.py` (was placeholder from Task 2.5)
- Create: `tests/integration/test_files_endpoints.py`

- [ ] **Step 1: Write the failing tests**

`tests/integration/test_files_endpoints.py`:

```python
from datetime import datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from jose import jwt as jose_jwt
from sqlalchemy import select

from app.core.config import settings
from app.models.tables.chat import Chat
from app.models.tables.user import User
from app.services.chat_service import ChatService


def _bearer(user_id: int, role: str = "user") -> dict[str, str]:
    token = jose_jwt.encode(
        {"user_id": user_id, "role": role, "type": "access",
         "exp": datetime.utcnow() + timedelta(minutes=5)},
        settings.jwt_secret_key, algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


async def _make_user_and_chats(db_session):
    user = User(email="x@x.com", phone=f"+1{uuid4().int % 1000000000:09d}",
                password_hash="x", role="user")
    db_session.add(user)
    await db_session.flush()
    await ChatService(db_session).ensure_user_chats(user.id)
    await db_session.flush()
    chat = (await db_session.execute(
        select(Chat).where(Chat.user_id == user.id, Chat.type == "main")
    )).scalar_one()
    return user, chat


@pytest.mark.integration
async def test_post_files_returns_presigned_url(db_session, client):
    user, chat = await _make_user_and_chats(db_session)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/files/",
        json={"chat_id": str(chat.id), "name": "x.txt", "mime": "text/plain", "size": 5},
        headers=_bearer(user.id),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["upload_url"].startswith("http")
    assert body["upload_method"] == "PUT"


@pytest.mark.integration
async def test_post_files_non_participant_403(db_session, client):
    user_a, chat_a = await _make_user_and_chats(db_session)
    user_b, _ = await _make_user_and_chats(db_session)
    await db_session.commit()

    # user_b tries to upload to user_a's chat.
    resp = await client.post(
        "/api/v1/files/",
        json={"chat_id": str(chat_a.id), "name": "x.txt", "mime": "text/plain", "size": 5},
        headers=_bearer(user_b.id),
    )
    assert resp.status_code == 403


@pytest.mark.integration
async def test_confirm_after_upload(db_session, client):
    user, chat = await _make_user_and_chats(db_session)
    await db_session.commit()

    presign = (await client.post(
        "/api/v1/files/",
        json={"chat_id": str(chat.id), "name": "h.txt", "mime": "text/plain", "size": 5},
        headers=_bearer(user.id),
    )).json()
    async with httpx.AsyncClient() as ac:
        await ac.put(presign["upload_url"], content=b"hello")

    confirm = await client.post(
        f"/api/v1/files/{presign['file_id']}/confirm/",
        headers=_bearer(user.id),
    )
    assert confirm.status_code == 200
```

- [ ] **Step 2: Run tests, expect failure**

Run: `uv run pytest tests/integration/test_files_endpoints.py -v -m integration`
Expected: FAIL — endpoints missing.

- [ ] **Step 3: Implement the router**

Replace `app/api/routers/files.py`:

```python
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.models.dto.chat import (
    FileMetaResponse,
    FilePresignRequest,
    FilePresignResponse,
)
from app.services.file_service import FileService, FileServiceError
from app.services.internal_token_service import InvalidToken, decode_access_token
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

router = APIRouter(prefix="/files", tags=["files"])
bearer_scheme = HTTPBearer()


def _decode_caller(creds: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    try:
        return decode_access_token(creds.credentials)
    except InvalidToken as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.post("/", response_model=FilePresignResponse)
async def request_upload(
    data: FilePresignRequest,
    caller=Depends(_decode_caller),
    session: AsyncSession = Depends(get_async_session),
) -> FilePresignResponse:
    svc = FileService(session)
    try:
        result = await svc.request_upload(
            uploader_user_id=caller.user_id,
            role=caller.role,
            chat_id=data.chat_id,
            name=data.name,
            mime=data.mime,
            size=data.size,
        )
    except FileServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    await session.commit()
    return FilePresignResponse(
        file_id=result.file_id,
        upload_url=result.upload_url,
        upload_method=result.upload_method,
        upload_headers=result.upload_headers,
        expires_at=result.expires_at,
    )


@router.post("/{file_id}/confirm/", status_code=status.HTTP_200_OK)
async def confirm_upload(
    file_id: UUID,
    caller=Depends(_decode_caller),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    svc = FileService(session)
    try:
        row = await svc.confirm_upload(file_id=file_id, caller_user_id=caller.user_id)
    except FileServiceError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    await session.commit()
    return {"file_id": str(row.id), "status": row.status}


@router.get("/{file_id}/", response_model=FileMetaResponse)
async def get_file_meta(
    file_id: UUID,
    caller=Depends(_decode_caller),
    session: AsyncSession = Depends(get_async_session),
) -> FileMetaResponse:
    from app.repositories.file_repository import FileRepository
    row = await FileRepository(session).get_by_id(file_id)
    if row is None:
        raise HTTPException(status_code=404, detail="file not found")
    # Authz: caller is participant of the file's chat. user => chat owner; support => any.
    from app.repositories.chat_repository import ChatRepository
    chat = await ChatRepository(session).get_by_id(row.chat_id)
    if caller.role == "user" and chat.user_id != caller.user_id:
        raise HTTPException(status_code=403, detail="forbidden")

    svc = FileService(session)
    url = await svc.make_presigned_get_url(row.object_key)
    return FileMetaResponse(file_id=row.id, name=row.name, mime=row.mime, size=row.size, url=url)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `uv run pytest tests/integration/test_files_endpoints.py -v -m integration`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/api/routers/files.py tests/integration/test_files_endpoints.py
git commit -m "files endpoints: presign upload, confirm, get meta"
```

### Task 5.5: Extend persist_message to support kind=file

**Files:**
- Modify: `app/services/chat_service.py`
- Modify: `app/api/routers/internal.py`
- Modify: `tests/integration/test_internal_messages.py` (add file scenarios)

- [ ] **Step 1: Write failing file-message tests**

Append to `tests/integration/test_internal_messages.py`:

```python
import httpx as _httpx
from uuid import uuid4 as _uuid4


async def _upload_file_for_chat(db_session, client, user, chat) -> str:
    """Returns file_id after presign + PUT + confirm."""
    from jose import jwt as jose_jwt
    from datetime import datetime, timedelta
    bearer = "Bearer " + jose_jwt.encode(
        {"user_id": user.id, "role": "user", "type": "access",
         "exp": datetime.utcnow() + timedelta(minutes=5)},
        settings.jwt_secret_key, algorithm=settings.jwt_algorithm,
    )
    presign = (await client.post(
        "/api/v1/files/",
        json={"chat_id": str(chat.id), "name": "h.txt", "mime": "text/plain", "size": 5},
        headers={"Authorization": bearer},
    )).json()
    async with _httpx.AsyncClient() as ac:
        await ac.put(presign["upload_url"], content=b"hello")
    confirm = await client.post(
        f"/api/v1/files/{presign['file_id']}/confirm/",
        headers={"Authorization": bearer},
    )
    assert confirm.status_code == 200
    return presign["file_id"]


@pytest.mark.integration
async def test_post_file_message_happy_path(db_session, client):
    user = await _make_user_with_chats(db_session)
    main_chat = (await db_session.execute(
        select(Chat).where(Chat.user_id == user.id, Chat.type == "main")
    )).scalar_one()
    await db_session.commit()

    file_id = await _upload_file_for_chat(db_session, client, user, main_chat)

    resp = await client.post(
        f"/internal/chats/{main_chat.id}/messages",
        json={
            "user_id": str(user.id), "role": "user", "kind": "file",
            "file_id": file_id, "client_msg_id": "fm-1",
        },
        headers=HEADERS,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "file"
    assert body["file"]["file_id"] == file_id
    assert body["file"]["url"].startswith("http")

    # File should now be linked.
    from app.models.tables.chat_file import ChatFile
    row = (await db_session.execute(
        select(ChatFile).where(ChatFile.id == file_id)
    )).scalar_one()
    assert row.status == "linked"


@pytest.mark.integration
async def test_file_message_with_pending_file_returns_400(db_session, client):
    user = await _make_user_with_chats(db_session)
    main_chat = (await db_session.execute(
        select(Chat).where(Chat.user_id == user.id, Chat.type == "main")
    )).scalar_one()
    await db_session.commit()

    # Presign but DO NOT confirm.
    from jose import jwt as jose_jwt
    from datetime import datetime, timedelta
    bearer = "Bearer " + jose_jwt.encode(
        {"user_id": user.id, "role": "user", "type": "access",
         "exp": datetime.utcnow() + timedelta(minutes=5)},
        settings.jwt_secret_key, algorithm=settings.jwt_algorithm,
    )
    presign = (await client.post(
        "/api/v1/files/",
        json={"chat_id": str(main_chat.id), "name": "h.txt", "mime": "text/plain", "size": 5},
        headers={"Authorization": bearer},
    )).json()

    resp = await client.post(
        f"/internal/chats/{main_chat.id}/messages",
        json={"user_id": str(user.id), "role": "user", "kind": "file", "file_id": presign["file_id"]},
        headers=HEADERS,
    )
    assert resp.status_code == 400


@pytest.mark.integration
async def test_file_message_wrong_owner_returns_400(db_session, client):
    user_a = await _make_user_with_chats(db_session)
    user_b = await _make_user_with_chats(db_session)
    chat_a = (await db_session.execute(
        select(Chat).where(Chat.user_id == user_a.id, Chat.type == "main")
    )).scalar_one()
    await db_session.commit()
    file_id = await _upload_file_for_chat(db_session, client, user_a, chat_a)

    # user_b tries to send user_a's file in user_a's chat.
    resp = await client.post(
        f"/internal/chats/{chat_a.id}/messages",
        json={"user_id": str(user_b.id), "role": "user", "kind": "file", "file_id": file_id},
        headers=HEADERS,
    )
    assert resp.status_code == 400


@pytest.mark.integration
async def test_file_message_relink_returns_400(db_session, client):
    user = await _make_user_with_chats(db_session)
    chat = (await db_session.execute(
        select(Chat).where(Chat.user_id == user.id, Chat.type == "main")
    )).scalar_one()
    await db_session.commit()
    file_id = await _upload_file_for_chat(db_session, client, user, chat)

    payload = {"user_id": str(user.id), "role": "user", "kind": "file", "file_id": file_id}
    first = await client.post(f"/internal/chats/{chat.id}/messages", json=payload, headers=HEADERS)
    assert first.status_code == 200
    second = await client.post(f"/internal/chats/{chat.id}/messages", json=payload, headers=HEADERS)
    assert second.status_code == 400
```

- [ ] **Step 2: Run tests, expect failure**

Run: `uv run pytest tests/integration/test_internal_messages.py -v -m integration -k file`
Expected: FAIL — `persist_message` raises `file messages not yet supported`.

- [ ] **Step 3: Extend persist_message for kind=file**

In `app/services/chat_service.py`, replace the `else` branch (the one that currently raises `"file messages not yet supported"`) with:

```python
    else:
        # kind == "file"
        if file_id is None:
            raise MessagePersistError("file_id required for kind=file")

        file_repo = FileRepository(self._session)
        file_row = await file_repo.get_by_id(file_id)
        if file_row is None:
            raise MessagePersistError("file_id not found")
        if file_row.user_id != sender_user_id:
            raise MessagePersistError("file_id not owned by sender")
        if file_row.chat_id != chat_id:
            raise MessagePersistError("file_id belongs to a different chat")
        if file_row.status == "pending":
            raise MessagePersistError("file not uploaded yet")
        if file_row.status == "linked":
            raise MessagePersistError("file already attached to a message")

        msg = await MessageRepository(self._session).insert(
            chat_id=chat_id,
            user_id=sender_user_id,
            role=role,
            kind=kind,
            body=None,
            file_id=file_id,
            client_msg_id=client_msg_id,
        )
        file_row.status = "linked"
        await self._session.flush()
        return msg
```

Add the import at the top of `chat_service.py`:

```python
from app.repositories.file_repository import FileRepository
```

- [ ] **Step 4: Update internal POST messages to attach FileMeta**

In `app/api/routers/internal.py`, update `post_internal_message` so that when `msg.kind == "file"`, the response includes a `FileMetaResponse` with a fresh presigned GET URL. Replace the `return CanonicalMessage(...)` block:

```python
    file_meta = None
    if msg.kind == "file" and msg.file_id is not None:
        from app.repositories.file_repository import FileRepository
        from app.services.file_service import FileService
        from app.models.dto.internal import FileMetaResponse
        file_row = await FileRepository(session).get_by_id(msg.file_id)
        url = await FileService(session).make_presigned_get_url(file_row.object_key)
        file_meta = FileMetaResponse(
            file_id=file_row.id,
            name=file_row.name,
            mime=file_row.mime,
            size=file_row.size,
            url=url,
        )

    return CanonicalMessage(
        id=msg.id,
        chat_id=msg.chat_id,
        user_id=str(msg.user_id),
        role=msg.role,
        kind=msg.kind,
        body=msg.body or "",
        file=file_meta,
        client_msg_id=msg.client_msg_id or "",
        created_at=msg.created_at,
    )
```

- [ ] **Step 5: Run tests, expect pass**

Run: `uv run pytest tests/integration/test_internal_messages.py -v -m integration`
Expected: all (9 total) passed.

- [ ] **Step 6: Commit**

```bash
git add app/services/chat_service.py app/api/routers/internal.py tests/integration/test_internal_messages.py
git commit -m "file messages: validation, transition to linked, presigned GET URL"
```

---

## Phase 6: Public chat endpoints

Goal: frontend can list chats, fetch history, and list files via REST. Two endpoints stay `not_implemented`.

### Task 6.1: Implement public chats router bodies

**Files:**
- Modify: `app/api/routers/chats.py`
- Create: `tests/integration/test_chats_endpoints.py`

- [ ] **Step 1: Write failing tests**

`tests/integration/test_chats_endpoints.py`:

```python
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from jose import jwt as jose_jwt
from sqlalchemy import select

from app.core.config import settings
from app.models.tables.chat import Chat
from app.models.tables.user import User
from app.services.chat_service import ChatService


def _bearer(user_id: int, role: str = "user") -> dict[str, str]:
    token = jose_jwt.encode(
        {"user_id": user_id, "role": role, "type": "access",
         "exp": datetime.utcnow() + timedelta(minutes=5)},
        settings.jwt_secret_key, algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


async def _seed_user(db_session) -> User:
    u = User(email="x@x.com", phone=f"+1{uuid4().int % 1000000000:09d}", password_hash="x", role="user")
    db_session.add(u)
    await db_session.flush()
    await ChatService(db_session).ensure_user_chats(u.id)
    await db_session.flush()
    return u


@pytest.mark.integration
async def test_get_chats_as_user_returns_two(db_session, client):
    user = await _seed_user(db_session)
    await db_session.commit()
    resp = await client.get("/api/v1/chats/", headers=_bearer(user.id))
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 2
    assert {i["type"] for i in items} == {"main", "sidequest"}


@pytest.mark.integration
async def test_post_chats_idempotent_returns_existing(db_session, client):
    user = await _seed_user(db_session)
    await db_session.commit()
    resp = await client.post(
        "/api/v1/chats/",
        json={"type": "main"},
        headers=_bearer(user.id),
    )
    assert resp.status_code in (200, 201)
    chat_id = resp.json()["id"]
    main_chat_id = (await db_session.execute(
        select(Chat.id).where(Chat.user_id == user.id, Chat.type == "main")
    )).scalar_one()
    assert chat_id == str(main_chat_id)


@pytest.mark.integration
async def test_get_messages_returns_empty_initially(db_session, client):
    user = await _seed_user(db_session)
    main_chat = (await db_session.execute(
        select(Chat).where(Chat.user_id == user.id, Chat.type == "main")
    )).scalar_one()
    await db_session.commit()
    resp = await client.get(
        f"/api/v1/chats/{main_chat.id}/messages/",
        headers=_bearer(user.id),
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.integration
async def test_get_messages_non_participant_returns_403(db_session, client):
    user_a = await _seed_user(db_session)
    user_b = await _seed_user(db_session)
    chat_a = (await db_session.execute(
        select(Chat).where(Chat.user_id == user_a.id, Chat.type == "main")
    )).scalar_one()
    await db_session.commit()
    resp = await client.get(
        f"/api/v1/chats/{chat_a.id}/messages/",
        headers=_bearer(user_b.id),
    )
    assert resp.status_code == 403


@pytest.mark.integration
async def test_post_message_returns_501(db_session, client):
    user = await _seed_user(db_session)
    main_chat = (await db_session.execute(
        select(Chat).where(Chat.user_id == user.id, Chat.type == "main")
    )).scalar_one()
    await db_session.commit()
    resp = await client.post(
        f"/api/v1/chats/{main_chat.id}/messages/",
        json={"body": "x"},
        headers=_bearer(user.id),
    )
    assert resp.status_code == 501


@pytest.mark.integration
async def test_mark_read_returns_501(db_session, client):
    user = await _seed_user(db_session)
    main_chat = (await db_session.execute(
        select(Chat).where(Chat.user_id == user.id, Chat.type == "main")
    )).scalar_one()
    await db_session.commit()
    resp = await client.post(
        f"/api/v1/chats/{main_chat.id}/read/",
        headers=_bearer(user.id),
    )
    assert resp.status_code == 501
```

- [ ] **Step 2: Run tests, expect failure**

Run: `uv run pytest tests/integration/test_chats_endpoints.py -v -m integration`
Expected: most fail — endpoints still return `not_implemented` or 401.

- [ ] **Step 3: Replace chats router bodies**

Replace `app/api/routers/chats.py`:

```python
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.utils import not_implemented
from app.core.database import get_async_session
from app.models.dto.chat import (
    ChatListItem,
    CounterpartInfo,
    FileMetaResponse,
    MessageHistoryItem,
    MessagePreview,
)
from app.models.tables.chat import Chat
from app.models.tables.message import Message
from app.models.tables.user import User
from app.repositories.chat_repository import ChatRepository
from app.repositories.file_repository import FileRepository
from app.repositories.message_repository import MessageRepository
from app.services.file_service import FileService
from app.services.internal_token_service import InvalidToken, decode_access_token

router = APIRouter(prefix="/chats", tags=["chats"])
bearer_scheme = HTTPBearer()


def _decode_caller(creds: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    try:
        return decode_access_token(creds.credentials)
    except InvalidToken as e:
        raise HTTPException(status_code=401, detail=str(e))


class ChatCreate(BaseModel):
    type: str
    manager_id: str | None = None


SUPPORT_PLACEHOLDER = CounterpartInfo(user_id=0, display_name="Support", role="support")


async def _customer_display_name(session: AsyncSession, user_id: int) -> str:
    result = await session.execute(select(User).where(User.id == user_id))
    u = result.scalar_one_or_none()
    if u is None:
        return f"User {user_id}"
    parts = [p for p in (u.first_name, u.last_name) if p]
    return " ".join(parts) if parts else f"User {user_id}"


async def _last_message_preview(session: AsyncSession, chat_id: UUID) -> tuple[MessagePreview | None, datetime | None]:
    msg = await MessageRepository(session).latest_for_chat(chat_id)
    if msg is None:
        return None, None
    file_name: str | None = None
    if msg.kind == "file" and msg.file_id is not None:
        f = await FileRepository(session).get_by_id(msg.file_id)
        file_name = f.name if f else None
    preview = MessagePreview(
        kind=msg.kind,
        body_preview=(msg.body[:120] if msg.body else None),
        file_name=file_name,
        created_at=msg.created_at,
    )
    return preview, msg.created_at


@router.get("/", response_model=list[ChatListItem])
async def list_chats(
    type: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    caller=Depends(_decode_caller),
    session: AsyncSession = Depends(get_async_session),
) -> list[ChatListItem]:
    repo = ChatRepository(session)

    if caller.role == "user":
        chats = await repo.list_chats_for_user(caller.user_id)
        if type:
            chats = [c for c in chats if c.type == type]
        items: list[ChatListItem] = []
        for c in chats:
            preview, last = await _last_message_preview(session, c.id)
            items.append(ChatListItem(
                id=c.id, type=c.type,
                counterpart=SUPPORT_PLACEHOLDER,
                last_message=preview,
                last_activity_at=last,
                unread_count=0,
            ))
        return items

    # role == "support": list all chats, paginated by last activity desc.
    stmt = select(Chat)
    if type:
        stmt = stmt.where(Chat.type == type)
    stmt = stmt.order_by(Chat.created_at.desc()).limit(limit)
    rows = list((await session.execute(stmt)).scalars().all())
    items = []
    for c in rows:
        preview, last = await _last_message_preview(session, c.id)
        display = await _customer_display_name(session, c.user_id)
        items.append(ChatListItem(
            id=c.id, type=c.type,
            counterpart=CounterpartInfo(user_id=c.user_id, display_name=display, role="user"),
            last_message=preview,
            last_activity_at=last,
            unread_count=0,
        ))
    return items


@router.post("/", status_code=status.HTTP_200_OK)
async def create_chat(
    payload: ChatCreate,
    caller=Depends(_decode_caller),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    if payload.type not in ("main", "sidequest"):
        raise HTTPException(status_code=400, detail="invalid chat type")
    if caller.role != "user":
        raise HTTPException(status_code=400, detail="support cannot create chats")
    chat = await ChatRepository(session).get_user_chat(caller.user_id, payload.type)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found (registration backfill missing)")
    return {"id": str(chat.id), "type": chat.type}


@router.get("/{chat_id}/messages/", response_model=list[MessageHistoryItem])
async def list_messages(
    chat_id: UUID,
    limit: int = Query(default=50, le=200),
    before: UUID | None = Query(default=None),
    caller=Depends(_decode_caller),
    session: AsyncSession = Depends(get_async_session),
) -> list[MessageHistoryItem]:
    chat = await ChatRepository(session).get_by_id(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")
    if caller.role == "user" and chat.user_id != caller.user_id:
        raise HTTPException(status_code=403, detail="forbidden")

    before_created_at: datetime | None = None
    if before is not None:
        anchor = (await session.execute(select(Message).where(Message.id == before))).scalar_one_or_none()
        if anchor is not None:
            before_created_at = anchor.created_at

    msgs = await MessageRepository(session).list_history(chat_id, limit=limit, before_created_at=before_created_at)
    file_svc = FileService(session)
    items: list[MessageHistoryItem] = []
    for m in msgs:
        file_meta = None
        if m.kind == "file" and m.file_id is not None:
            f = await FileRepository(session).get_by_id(m.file_id)
            if f:
                url = await file_svc.make_presigned_get_url(f.object_key)
                file_meta = FileMetaResponse(file_id=f.id, name=f.name, mime=f.mime, size=f.size, url=url)
        items.append(MessageHistoryItem(
            id=m.id, chat_id=m.chat_id, user_id=m.user_id, role=m.role,
            kind=m.kind, body=m.body, file=file_meta,
            client_msg_id=m.client_msg_id, created_at=m.created_at,
        ))
    return items


@router.post("/{chat_id}/messages/")
async def post_message(chat_id: UUID, payload: dict) -> None:
    not_implemented("REST message send is out of scope; use the WebSocket channel via chatgw")


@router.post("/{chat_id}/read/", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(chat_id: UUID) -> None:
    not_implemented("Read tracking is out of scope for v1")


@router.get("/{chat_id}/files/", response_model=list[FileMetaResponse])
async def list_chat_files(
    chat_id: UUID,
    caller=Depends(_decode_caller),
    session: AsyncSession = Depends(get_async_session),
) -> list[FileMetaResponse]:
    chat = await ChatRepository(session).get_by_id(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")
    if caller.role == "user" and chat.user_id != caller.user_id:
        raise HTTPException(status_code=403, detail="forbidden")
    rows = await FileRepository(session).list_for_chat(chat_id)
    svc = FileService(session)
    out = []
    for r in rows:
        url = await svc.make_presigned_get_url(r.object_key)
        out.append(FileMetaResponse(file_id=r.id, name=r.name, mime=r.mime, size=r.size, url=url))
    return out
```

- [ ] **Step 4: Run tests, expect pass**

Run: `uv run pytest tests/integration/test_chats_endpoints.py -v -m integration`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add app/api/routers/chats.py tests/integration/test_chats_endpoints.py
git commit -m "implement public chat list/history/files; leave send and mark-read stubbed"
```

---

## Phase 7: Support seeder CLI

### Task 7.1: create_support_user.py

**Files:**
- Create: `app/scripts/__init__.py`
- Create: `app/scripts/create_support_user.py`

- [ ] **Step 1: Create the package init**

```bash
mkdir -p app/scripts
touch app/scripts/__init__.py
```

- [ ] **Step 2: Write the CLI**

`app/scripts/create_support_user.py`:

```python
"""Seed a support-role user.

Usage:
    uv run python -m app.scripts.create_support_user \
        --login alice --email alice@example.com \
        --phone +10000000000 --password 'changeme'

Add --reset-password to update an existing support user's password.
"""
import argparse
import asyncio
import sys

from passlib.context import CryptContext
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.tables.user import User
from app.services.chat_service import ChatService

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def _run(args: argparse.Namespace) -> int:
    async with AsyncSessionLocal() as session:
        existing = (await session.execute(
            select(User).where(User.login == args.login)
        )).scalar_one_or_none()

        if existing:
            if not args.reset_password:
                print(f"user with login={args.login!r} already exists; use --reset-password to update", file=sys.stderr)
                return 1
            existing.password_hash = pwd_context.hash(args.password)
            await session.commit()
            print(f"updated password for support user {args.login!r} (id={existing.id})")
            return 0

        user = User(
            email=args.email,
            phone=args.phone,
            password_hash=pwd_context.hash(args.password),
            first_name=args.first_name,
            last_name=args.last_name,
            role="support",
            login=args.login,
        )
        session.add(user)
        await session.flush()
        await ChatService(session).ensure_user_chats(user.id)
        await session.commit()
        print(f"created support user {args.login!r} (id={user.id})")
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or update a support-role user.")
    parser.add_argument("--login", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--phone", required=True, help="Contact number (NOT used for SMS auth)")
    parser.add_argument("--password", required=True)
    parser.add_argument("--first-name", default=None)
    parser.add_argument("--last-name", default=None)
    parser.add_argument("--reset-password", action="store_true")
    args = parser.parse_args()
    rc = asyncio.run(_run(args))
    sys.exit(rc)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Test it against the dev DB**

```bash
uv run python -m app.scripts.create_support_user \
    --login alice --email alice@example.com \
    --phone +10000000001 --password 'changeme'
```

Expected: `created support user 'alice' (id=...)`.

Run a second time to verify the duplicate-prevention:

```bash
uv run python -m app.scripts.create_support_user \
    --login alice --email alice@example.com \
    --phone +10000000001 --password 'changeme'
```

Expected: `user with login='alice' already exists; use --reset-password to update`, exit code 1.

Run with `--reset-password`:

```bash
uv run python -m app.scripts.create_support_user \
    --login alice --email alice@example.com \
    --phone +10000000001 --password 'newpw' --reset-password
```

Expected: `updated password for support user 'alice' (id=...)`.

- [ ] **Step 4: Commit**

```bash
git add app/scripts/
git commit -m "CLI: create_support_user with --reset-password"
```

---

## Phase 8: Final wiring & docs

### Task 8.1: tests/README.md with manual smoke checklist

**Files:**
- Create: `tests/README.md`

- [ ] **Step 1: Write the README**

```markdown
# Tests

## Layout

- `tests/unit/` — fast, in-process; some require DB and MinIO (marked `@pytest.mark.integration`).
- `tests/integration/` — full HTTP path via httpx ASGITransport + real DB + real MinIO.
- `tests/migrations/` — Alembic migration verification.

## Prerequisites

Postgres, Redis, and MinIO must be running. The simplest path:

```bash
docker compose up -d database redis minio minio-init
```

Then run the suite:

```bash
uv run alembic upgrade head            # against the dev DB; conftest handles the test DB
uv run pytest -q                       # full suite (creates and migrates *_test DB on first run)
uv run pytest tests/unit -q -m "not integration"   # fast subset
```

## Manual end-to-end smoke

The Go side lives in `../InsurancePlatform`. To verify the full chat round-trip:

1. `docker compose up -d` everything in this project.
2. Run migrations: `docker compose run --rm alembic`.
3. Seed a support user:

   ```bash
   uv run python -m app.scripts.create_support_user \
       --login alice --email alice@example.com \
       --phone +10000000001 --password 'changeme'
   ```

4. Register a customer through `POST /api/v1/auth/request-code/` then `POST /api/v1/auth/register/`.
5. Start Go:

   ```bash
   cd ../InsurancePlatform
   CHATGW_PYTHON_BASE_URL=http://localhost:8000 \
   CHATGW_INTERNAL_SECRET="$(grep ^INTERNAL_SECRET ../InsurancePlatformPy/.env | cut -d= -f2)" \
   go run ./cmd/chatgw
   ```

6. Open the React harness; log in as customer and as support in two browser windows.
7. Send a text message from customer → assert support receives it; reply from support → assert customer receives.
8. Upload a file from customer → assert support sees the file render with the presigned URL.
9. Disconnect Go (Ctrl-C), send a message attempt, restart Go, reconnect → assert ordering and no duplication.
```

- [ ] **Step 2: Commit**

```bash
git add tests/README.md
git commit -m "tests README with run commands and manual smoke checklist"
```

---

## Self-review

Per the writing-plans skill: I reviewed the plan against the spec.

**Spec coverage:** Every spec section maps to one or more tasks.
- Section 3 (module layout) → file structure block above.
- Section 4 (data model) → Tasks 1.1–1.6.
- Section 5.1 (internal endpoints) → Tasks 4.1, 4.2, 5.5.
- Section 5.2 (support auth) → Tasks 2.4, 2.5.
- Section 5.3 (public chat endpoints) → Task 6.1.
- Section 5.4 (files endpoints) → Tasks 5.3, 5.4.
- Section 6 (critical flows) → covered by integration tests in Tasks 4.1, 4.2, 5.4, 5.5.
- Section 7 (auth, secrets, config) → Tasks 2.1, 2.2, 2.3, plus settings in Task 0.2.
- Section 8 (infra) → Tasks 0.3, 0.4.
- Section 9 (error handling) → status codes asserted in integration tests; `MessagePersistError`/`FileServiceError`/`ChatResolutionError` carry status_code + code.
- Section 10 (testing) → Tasks 0.5 (conftest), plus every Task's tests.
- CLI seeder (Section 7.6) → Task 7.1.

**Placeholder scan:** none. All steps contain concrete code or exact commands.

**Type consistency:** `ChatResolutionError`, `MessagePersistError`, `FileServiceError`, `InvalidToken`, `DecodedToken` consistent across tasks. `make_access_token`, `create_refresh_token`, `decode_access_token` signatures referenced consistently. `WsValidateRequest`/`Response`, `InternalMessageRequest`, `CanonicalMessage`, `FileMetaResponse`, `FilePresignRequest`/`Response`, `ChatListItem`, `MessagePreview`, `CounterpartInfo`, `MessageHistoryItem` defined once and reused. Pagination cursor for `/chats/{id}/messages/` uses `?before=<msg_id>` (UUID) consistent with the spec's "raw message UUID" decision.

---

## Notes for the executor

- **Run integration tests against the docker-compose services**, not against a randomly chosen Postgres/MinIO. The conftest assumes the `settings.minio_endpoint` is reachable.
- **Commit after every task.** That's by design — each commit is a small, reviewable step.
- The Go side does not need to be touched in this plan. Its env vars (`CHATGW_PYTHON_BASE_URL`, `CHATGW_INTERNAL_SECRET`) must match what's in this project's `.env`.
- **Don't refactor existing code unless explicitly instructed.** The user's standing preference for this project is additive-over-invasive — see `memory/feedback_python_additive.md`.
- If a test fails for environmental reasons (e.g., MinIO not running), bring up the service and retry — don't change the test to skip.
- If you hit a real spec gap not covered by a task, surface it before guessing.
