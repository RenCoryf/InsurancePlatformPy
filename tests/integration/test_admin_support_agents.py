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
