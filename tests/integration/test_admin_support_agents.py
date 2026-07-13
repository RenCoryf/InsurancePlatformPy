import pytest

from app.models.tables.support_agent import SupportAgent
from tests.conftest import _create_agent, make_support_jwt


@pytest.mark.asyncio
async def test_create_list_update_delete_flow(client, admin_headers):
    headers = admin_headers

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
    assert created["role"] == "manager"
    aid = created["id"]

    # Duplicate login -> 409
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


@pytest.mark.asyncio
async def test_admin_endpoint_rejects_manager_role(client, db_session):
    manager = await _create_agent(db_session, login="just-manager", role=SupportAgent.ROLE_MANAGER)
    headers = {"Authorization": f"Bearer {make_support_jwt(manager.id)}"}
    r = await client.get("/api/v1/admin/support-agents/", headers=headers)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_cannot_deactivate_owner(client, db_session, admin_headers, owner_agent):
    r = await client.patch(
        f"/api/v1/admin/support-agents/{owner_agent.id}/",
        json={"is_active": False},
        headers=admin_headers,
    )
    assert r.status_code == 409
    r2 = await client.delete(
        f"/api/v1/admin/support-agents/{owner_agent.id}/", headers=admin_headers
    )
    assert r2.status_code == 409
