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
