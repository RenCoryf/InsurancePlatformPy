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
