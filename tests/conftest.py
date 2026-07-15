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
from datetime import datetime, timedelta
from typing import AsyncIterator

import httpx
import pytest
from jose import jwt as jose_jwt
from passlib.context import CryptContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Force the test database name BEFORE importing app.* (config reads env at import).
os.environ.setdefault("DB_NAME", "insurance_platform_test")

from app.api.deps.redis_dep import get_redis  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.database import get_async_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models.tables.support_agent import SupportAgent  # noqa: E402

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


class FakeRedis:
    """Минимальный async-Redis для тестов: get/set/delete/incr/expire."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value
        return True

    async def delete(self, *keys):
        removed = 0
        for key in keys:
            if self.store.pop(key, None) is not None:
                removed += 1
        return removed

    async def incr(self, key):
        value = int(self.store.get(key, "0")) + 1
        self.store[key] = str(value)
        return value

    async def expire(self, key, ttl):
        return True


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
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
async def client(db_session, fake_redis) -> AsyncIterator[httpx.AsyncClient]:
    """FastAPI test client. Overrides get_async_session to use the test transaction
    and get_redis to use the in-memory FakeRedis (lifespan does not run here)."""

    async def _override():
        yield db_session

    async def _override_redis():
        return fake_redis

    app.dependency_overrides[get_async_session] = _override
    app.dependency_overrides[get_redis] = _override_redis
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


def make_support_jwt(agent_id: int) -> str:
    now = datetime.utcnow()
    payload = {
        "sub": f"support:{agent_id}",
        "role": "support",
        "type": "access",
        "exp": now + timedelta(minutes=settings.jwt_access_token_expire_minutes),
        "iat": now,
    }
    return jose_jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def make_user_jwt(user_id: int) -> str:
    now = datetime.utcnow()
    payload = {
        "user_id": user_id,
        "sub": f"user:{user_id}",
        "role": "user",
        "type": "access",
        "exp": now + timedelta(minutes=settings.jwt_access_token_expire_minutes),
        "iat": now,
    }
    return jose_jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


async def _create_agent(db_session, *, login: str, role: str, is_owner: bool = False,
                        permissions: list[str] | None = None, password: str = "p4ssw0rd1") -> SupportAgent:
    agent = SupportAgent(
        login=login,
        password_hash=_pwd.hash(password),
        display_name=login.title(),
        role=role,
        is_owner=is_owner,
        permissions=permissions or [],
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


@pytest.fixture
async def admin_agent(db_session) -> SupportAgent:
    return await _create_agent(db_session, login="admin-fixture", role=SupportAgent.ROLE_ADMIN)


@pytest.fixture
async def owner_agent(db_session) -> SupportAgent:
    return await _create_agent(
        db_session, login="owner-fixture", role=SupportAgent.ROLE_ADMIN, is_owner=True
    )


@pytest.fixture
def admin_headers(admin_agent) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_support_jwt(admin_agent.id)}"}


@pytest.fixture
def owner_headers(owner_agent) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_support_jwt(owner_agent.id)}"}


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
