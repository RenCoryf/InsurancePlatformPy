"""Создание менеджеров/администраторов с SMS-инвайтом и установка пароля
по одноразовому токену."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.tables.support_agent import SupportAgent


def _manager_payload(**overrides) -> dict:
    payload = {
        "login": "new-manager",
        "display_name": "Новый менеджер",
        "phone": "79990004001",
        "role": "manager",
        "permissions": ["chats", "users_view"],
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_invite_flow_end_to_end(client, db_session, admin_headers):
    # Создание менеджера → инвайт
    r = await client.post("/api/v1/admin/managers/", json=_manager_payload(), headers=admin_headers)
    assert r.status_code == 201, r.text
    body = r.json()
    token = body["invite_token"]
    assert token
    assert "/invite/" in body["invite_link"]
    assert body["agent"]["role"] == "manager"
    assert body["agent"]["permissions"] == ["chats", "users_view"]

    # Аудит manager_create
    rows = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == AuditLog.ACTION_MANAGER_CREATE,
            AuditLog.target_id == str(body["agent"]["id"]),
        )
    )
    assert rows.scalars().first() is not None

    # До установки пароля вход невозможен
    r_login = await client.post(
        "/api/v1/support/login/", json={"login": "new-manager", "password": "MyNewPass1"}
    )
    assert r_login.status_code == 401

    # Установка пароля по токену
    r_accept = await client.post(
        "/api/v1/support/invite/accept/",
        json={"token": token, "password": "MyNewPass1"},
    )
    assert r_accept.status_code == 200, r_accept.text

    # Токен одноразовый
    r_again = await client.post(
        "/api/v1/support/invite/accept/",
        json={"token": token, "password": "Другой1234"},
    )
    assert r_again.status_code == 404

    # Теперь вход работает
    r_login2 = await client.post(
        "/api/v1/support/login/", json={"login": "new-manager", "password": "MyNewPass1"}
    )
    assert r_login2.status_code == 200, r_login2.text
    assert r_login2.json()["access_token"]


@pytest.mark.asyncio
async def test_create_admin_requires_owner(client, admin_headers, owner_headers):
    payload = _manager_payload(login="new-admin", phone="79990004002", role="admin")

    r = await client.post("/api/v1/admin/managers/", json=payload, headers=admin_headers)
    assert r.status_code == 403

    r2 = await client.post("/api/v1/admin/managers/", json=payload, headers=owner_headers)
    assert r2.status_code == 201, r2.text
    assert r2.json()["agent"]["role"] == "admin"


@pytest.mark.asyncio
async def test_expired_invite_rejected(client, db_session, admin_headers):
    r = await client.post(
        "/api/v1/admin/managers/",
        json=_manager_payload(login="late-manager", phone="79990004003"),
        headers=admin_headers,
    )
    token = r.json()["invite_token"]

    row = await db_session.execute(
        select(SupportAgent).where(SupportAgent.login == "late-manager")
    )
    agent = row.scalar_one()
    agent.invite_expires_at = datetime.utcnow() - timedelta(hours=1)
    await db_session.commit()

    r_accept = await client.post(
        "/api/v1/support/invite/accept/",
        json={"token": token, "password": "MyNewPass1"},
    )
    assert r_accept.status_code == 410


@pytest.mark.asyncio
async def test_duplicate_login_or_phone_rejected(client, admin_headers):
    r1 = await client.post(
        "/api/v1/admin/managers/",
        json=_manager_payload(login="dup-manager", phone="79990004004"),
        headers=admin_headers,
    )
    assert r1.status_code == 201

    r2 = await client.post(
        "/api/v1/admin/managers/",
        json=_manager_payload(login="dup-manager", phone="79990004005"),
        headers=admin_headers,
    )
    assert r2.status_code == 409

    r3 = await client.post(
        "/api/v1/admin/managers/",
        json=_manager_payload(login="other-manager", phone="79990004004"),
        headers=admin_headers,
    )
    assert r3.status_code == 409


@pytest.mark.asyncio
async def test_unknown_permission_rejected(client, admin_headers):
    r = await client.post(
        "/api/v1/admin/managers/",
        json=_manager_payload(login="perm-manager", phone="79990004006", permissions=["superpower"]),
        headers=admin_headers,
    )
    assert r.status_code == 422
