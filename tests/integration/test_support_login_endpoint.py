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
