"""Настройки платформы: чтение/обновление через админ-API, корневая
реферальная ссылка, аудит изменений, Redis-кеш SettingsService."""

import json
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.services.settings_service import CACHE_KEY, SettingsService
from tests.conftest import FakeRedis

CODE = "123456"


@pytest.mark.asyncio
async def test_get_settings_returns_defaults(client, admin_headers):
    r = await client.get("/api/v1/admin/settings/", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert Decimal(str(body["bonus_level_1_percent"])) == Decimal("3.0")
    assert Decimal(str(body["bonus_level_2_percent"])) == Decimal("3.0")
    assert Decimal(str(body["bonus_level_3_percent"])) == Decimal("2.0")
    assert Decimal(str(body["bonus_level_4_percent"])) == Decimal("1.0")
    assert body["bonus_accrual_delay_days"] == 15
    assert Decimal(str(body["bonus_min_exchange"])) == Decimal("1000")
    assert body["blocked_user_level_rule"] == "zero"
    assert body["sms_daily_limit_per_user"] == 5
    assert body["root_referral_active"] is False


@pytest.mark.asyncio
async def test_patch_settings_updates_and_audits(client, db_session, admin_headers):
    r = await client.patch(
        "/api/v1/admin/settings/",
        json={"bonus_accrual_delay_days": 30, "sms_daily_limit_per_user": 10},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["bonus_accrual_delay_days"] == 30
    assert r.json()["sms_daily_limit_per_user"] == 10

    rows = await db_session.execute(
        select(AuditLog).where(AuditLog.action == AuditLog.ACTION_SETTINGS_UPDATE)
    )
    audits = list(rows.scalars().all())
    assert audits, "settings_update должен попадать в audit_log"
    assert audits[-1].new_value["bonus_accrual_delay_days"] == "30"

    r2 = await client.get("/api/v1/admin/settings/", headers=admin_headers)
    assert r2.json()["bonus_accrual_delay_days"] == 30


@pytest.mark.asyncio
async def test_patch_settings_rejects_bad_rule(client, admin_headers):
    r = await client.patch(
        "/api/v1/admin/settings/",
        json={"blocked_user_level_rule": "bogus"},
        headers=admin_headers,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_settings_require_admin(client):
    r = await client.get("/api/v1/admin/settings/")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_root_referral_generate_register_revoke(client, db_session, fake_redis, admin_headers):
    # Генерация
    r = await client.post("/api/v1/admin/settings/root-referral/generate/", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    code = body["root_referral_code"]
    assert code and len(code) == 12
    assert body["root_referral_active"] is True
    assert code in body["root_referral_link"]

    # Регистрация по корневой ссылке → referrer_id NULL
    fake_redis.store["otp:79990003001"] = json.dumps({"code": CODE, "attempts": 0})
    r_reg = await client.post(
        "/api/v1/auth/register/",
        json={
            "phone": "79990003001",
            "code": CODE,
            "email": "root-reg@example.com",
            "password": "Password1",
            "referral_code": code,
        },
    )
    assert r_reg.status_code == 201, r_reg.text

    from app.models.users.entities import User

    row = await db_session.execute(select(User).where(User.id == r_reg.json()["user"]["id"]))
    assert row.scalar_one().referrer_id is None

    # Отзыв
    r_rev = await client.post("/api/v1/admin/settings/root-referral/revoke/", headers=admin_headers)
    assert r_rev.status_code == 200
    assert r_rev.json()["root_referral_active"] is False
    assert r_rev.json()["root_referral_code"] is None

    # Старый корневой код больше не работает
    fake_redis.store["otp:79990003002"] = json.dumps({"code": CODE, "attempts": 0})
    r_reg2 = await client.post(
        "/api/v1/auth/register/",
        json={
            "phone": "79990003002",
            "code": CODE,
            "email": "root-reg2@example.com",
            "password": "Password1",
            "referral_code": code,
        },
    )
    assert r_reg2.status_code == 422


@pytest.mark.asyncio
async def test_settings_service_cache_roundtrip(db_session):
    redis = FakeRedis()
    svc = SettingsService(db_session, redis)

    values = await svc.get_values()
    assert values["sms_daily_limit_per_user"] == 5
    assert CACHE_KEY in redis.store  # кеш наполнен

    # Обновление инвалидирует кеш
    await svc.update({"sms_daily_limit_per_user": 7})
    assert CACHE_KEY not in redis.store

    values2 = await svc.get_values()
    assert values2["sms_daily_limit_per_user"] == 7
    assert values2["bonus_min_exchange"] == Decimal("1000")


@pytest.mark.asyncio
async def test_settings_service_rejects_unknown_field(db_session):
    svc = SettingsService(db_session)
    with pytest.raises(ValueError):
        await svc.update({"no_such_field": 1})
