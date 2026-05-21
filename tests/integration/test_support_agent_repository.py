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
