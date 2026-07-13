"""Админ-модерация пользователей: блокировка, разблокировка, удаление
с двойным подтверждением; записи в audit_log."""

import json

import pytest
from passlib.context import CryptContext
from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.tables.support_agent import SupportAgent
from app.models.users.entities import User
from tests.conftest import _create_agent, make_support_jwt

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

PASSWORD = "Password1"
PASSWORD_HASH = pwd.hash(PASSWORD)
CODE = "123456"


async def _make_user(db_session, *, phone: str, referral_code: str) -> User:
    user = User(
        email=f"u{phone}@example.com",
        phone=phone,
        password_hash=PASSWORD_HASH,
        referral_code=referral_code,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _audit_rows(db_session, action: str, target_id: str) -> list[AuditLog]:
    rows = await db_session.execute(
        select(AuditLog).where(AuditLog.action == action, AuditLog.target_id == target_id)
    )
    return list(rows.scalars().all())


@pytest.mark.asyncio
async def test_block_and_unblock_flow(client, db_session, fake_redis, admin_agent, admin_headers):
    user = await _make_user(db_session, phone="79990002001", referral_code="MODBLK01")

    # Блокировка
    r = await client.post(
        f"/api/v1/admin/users/{user.id}/block/",
        json={"reason": "fraud", "comment": "подозрительные операции"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "blocked"
    assert body["blocked_reason"] == "fraud"
    assert body["blocked_by_admin_id"] == admin_agent.id
    assert body["blocked_at"] is not None

    # Запись в audit_log есть
    audits = await _audit_rows(db_session, AuditLog.ACTION_USER_BLOCK, str(user.id))
    assert len(audits) == 1
    assert audits[0].performed_by_id == admin_agent.id
    assert audits[0].new_value["reason"] == "fraud"
    assert audits[0].comment == "подозрительные операции"

    # Логин заблокированного → 403
    fake_redis.store[f"otp:{user.phone}"] = json.dumps({"code": CODE, "attempts": 0})
    r_login = await client.post(
        "/api/v1/auth/login/",
        json={"phone": user.phone, "code": CODE, "password": PASSWORD},
    )
    assert r_login.status_code == 403

    # Повторная блокировка → 409
    r_again = await client.post(
        f"/api/v1/admin/users/{user.id}/block/",
        json={"reason": "spam"},
        headers=admin_headers,
    )
    assert r_again.status_code == 409

    # Разблокировка
    r_un = await client.post(f"/api/v1/admin/users/{user.id}/unblock/", headers=admin_headers)
    assert r_un.status_code == 200
    assert r_un.json()["status"] == "active"
    assert r_un.json()["blocked_reason"] is None
    assert await _audit_rows(db_session, AuditLog.ACTION_USER_UNBLOCK, str(user.id))

    # Логин снова работает
    fake_redis.store[f"otp:{user.phone}"] = json.dumps({"code": CODE, "attempts": 0})
    r_login2 = await client.post(
        "/api/v1/auth/login/",
        json={"phone": user.phone, "code": CODE, "password": PASSWORD},
    )
    assert r_login2.status_code == 200, r_login2.text


@pytest.mark.asyncio
async def test_block_with_invalid_reason_rejected(client, db_session, admin_headers):
    user = await _make_user(db_session, phone="79990002002", referral_code="MODBLK02")
    r = await client.post(
        f"/api/v1/admin/users/{user.id}/block/",
        json={"reason": "unknown-reason"},
        headers=admin_headers,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_block_requires_admin_role(client, db_session):
    user = await _make_user(db_session, phone="79990002003", referral_code="MODBLK03")
    manager = await _create_agent(db_session, login="mod-manager", role=SupportAgent.ROLE_MANAGER)
    headers = {"Authorization": f"Bearer {make_support_jwt(manager.id)}"}

    r = await client.post(
        f"/api/v1/admin/users/{user.id}/block/", json={"reason": "spam"}, headers=headers
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_delete_user_requires_double_confirmation(client, db_session, fake_redis, admin_headers):
    user = await _make_user(db_session, phone="79990002004", referral_code="MODDEL01")

    # Шаг 1: без confirm_token — удаления нет, выдан токен
    r1 = await client.delete(f"/api/v1/admin/users/{user.id}/", headers=admin_headers)
    assert r1.status_code == 200, r1.text
    body = r1.json()
    assert body["confirm_required"] is True
    token = body["confirm_token"]

    await db_session.refresh(user)
    assert user.status == User.STATUS_ACTIVE  # ещё не удалён

    # Шаг 2: с confirm_token — анонимизация
    r2 = await client.delete(
        f"/api/v1/admin/users/{user.id}/",
        params={"confirm_token": token},
        headers=admin_headers,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "deleted"

    await db_session.refresh(user)
    assert user.status == User.STATUS_DELETED
    assert user.first_name == f"Удалённый пользователь #{user.id}"
    assert user.phone is None
    assert user.email is None
    assert user.last_name is None

    assert await _audit_rows(db_session, AuditLog.ACTION_USER_DELETE, str(user.id))

    # Реферальная ссылка удалённого недействительна
    fake_redis.store["otp:79990002005"] = json.dumps({"code": CODE, "attempts": 0})
    r_reg = await client.post(
        "/api/v1/auth/register/",
        json={
            "phone": "79990002005",
            "code": CODE,
            "email": "x@example.com",
            "password": PASSWORD,
            "referral_code": "MODDEL01",
        },
    )
    assert r_reg.status_code == 422
    assert r_reg.json() == {"error": "Реферальная ссылка недействительна"}

    # Повторное удаление → 409
    r3 = await client.delete(f"/api/v1/admin/users/{user.id}/", headers=admin_headers)
    assert r3.status_code == 409


@pytest.mark.asyncio
async def test_delete_user_with_invalid_token_rejected(client, db_session, admin_headers):
    user = await _make_user(db_session, phone="79990002006", referral_code="MODDEL02")
    r = await client.delete(
        f"/api/v1/admin/users/{user.id}/",
        params={"confirm_token": "garbage"},
        headers=admin_headers,
    )
    assert r.status_code == 400

    other = await _make_user(db_session, phone="79990002007", referral_code="MODDEL03")
    r_tok = await client.delete(f"/api/v1/admin/users/{other.id}/", headers=admin_headers)
    token_for_other = r_tok.json()["confirm_token"]

    # Токен выписан на другого пользователя
    r2 = await client.delete(
        f"/api/v1/admin/users/{user.id}/",
        params={"confirm_token": token_for_other},
        headers=admin_headers,
    )
    assert r2.status_code == 400
