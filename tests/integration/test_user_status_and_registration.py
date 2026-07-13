"""Блокировки/удаление пользователей и регистрация по реферальным ссылкам.

OTP-коды лежат в FakeRedis (fixture ``fake_redis``), который подменяет
Redis-зависимость приложения в fixture ``client``.
"""

import json

import pytest
from passlib.context import CryptContext
from sqlalchemy import select

from app.models.users.entities import User
from app.services.settings_service import SettingsService
from tests.conftest import make_user_jwt

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

PASSWORD = "Password1"
PASSWORD_HASH = pwd.hash(PASSWORD)
CODE = "123456"

REFERRAL_INVALID = {"error": "Реферальная ссылка недействительна"}


def _put_otp(fake_redis, phone: str, code: str = CODE) -> None:
    fake_redis.store[f"otp:{phone}"] = json.dumps({"code": code, "attempts": 0})


async def _make_user(db_session, *, phone: str, referral_code: str, status: str = "active", **kw) -> User:
    user = User(
        email=f"u{phone}@example.com",
        phone=phone,
        password_hash=PASSWORD_HASH,
        referral_code=referral_code,
        status=status,
        **kw,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def _register_payload(phone: str, referral_code: str) -> dict:
    return {
        "phone": phone,
        "code": CODE,
        "email": f"new{phone}@example.com",
        "password": PASSWORD,
        "first_name": "Иван",
        "referral_code": referral_code,
    }


# ---------------------------------------------------------------------------
# Регистрация по реферальным ссылкам
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_via_root_code_sets_null_referrer(client, db_session, fake_redis):
    await SettingsService(db_session).update(
        {"root_referral_code": "ROOTCODE2026", "root_referral_active": True}
    )
    phone = "79990001001"
    _put_otp(fake_redis, phone)

    r = await client.post("/api/v1/auth/register/", json=_register_payload(phone, "ROOTCODE2026"))
    assert r.status_code == 201, r.text
    user_id = r.json()["user"]["id"]

    row = await db_session.execute(select(User).where(User.id == user_id))
    user = row.scalar_one()
    assert user.referrer_id is None
    assert user.status == User.STATUS_ACTIVE


@pytest.mark.asyncio
async def test_register_via_inactive_root_code_rejected(client, db_session, fake_redis):
    await SettingsService(db_session).update(
        {"root_referral_code": "ROOTCODE2026", "root_referral_active": False}
    )
    phone = "79990001002"
    _put_otp(fake_redis, phone)

    r = await client.post("/api/v1/auth/register/", json=_register_payload(phone, "ROOTCODE2026"))
    assert r.status_code == 422
    assert r.json() == REFERRAL_INVALID


@pytest.mark.asyncio
async def test_register_via_active_referrer(client, db_session, fake_redis):
    referrer = await _make_user(db_session, phone="79990001003", referral_code="ACTREF01")
    phone = "79990001004"
    _put_otp(fake_redis, phone)

    r = await client.post("/api/v1/auth/register/", json=_register_payload(phone, "ACTREF01"))
    assert r.status_code == 201, r.text

    row = await db_session.execute(select(User).where(User.id == r.json()["user"]["id"]))
    assert row.scalar_one().referrer_id == referrer.id


@pytest.mark.asyncio
async def test_register_via_blocked_referrer_rejected(client, db_session, fake_redis):
    await _make_user(db_session, phone="79990001005", referral_code="BLKREF01", status=User.STATUS_BLOCKED)
    phone = "79990001006"
    _put_otp(fake_redis, phone)

    r = await client.post("/api/v1/auth/register/", json=_register_payload(phone, "BLKREF01"))
    assert r.status_code == 422
    assert r.json() == REFERRAL_INVALID


@pytest.mark.asyncio
async def test_register_via_deleted_referrer_rejected(client, db_session, fake_redis):
    await _make_user(db_session, phone="79990001007", referral_code="DELREF01", status=User.STATUS_DELETED)
    phone = "79990001008"
    _put_otp(fake_redis, phone)

    r = await client.post("/api/v1/auth/register/", json=_register_payload(phone, "DELREF01"))
    assert r.status_code == 422
    assert r.json() == REFERRAL_INVALID


@pytest.mark.asyncio
async def test_register_unknown_referral_code_rejected(client, fake_redis):
    phone = "79990001009"
    _put_otp(fake_redis, phone)

    r = await client.post("/api/v1/auth/register/", json=_register_payload(phone, "NOSUCHREF"))
    assert r.status_code == 422
    assert r.json() == REFERRAL_INVALID


@pytest.mark.asyncio
async def test_register_without_referral_code_rejected(client, fake_redis):
    phone = "79990001010"
    _put_otp(fake_redis, phone)
    payload = _register_payload(phone, "IGNORED")
    del payload["referral_code"]

    r = await client.post("/api/v1/auth/register/", json=payload)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_register_wrong_code_rejected(client, db_session, fake_redis):
    await _make_user(db_session, phone="79990001011", referral_code="OKREF001")
    phone = "79990001012"
    _put_otp(fake_redis, phone, code="654321")

    r = await client.post("/api/v1/auth/register/", json=_register_payload(phone, "OKREF001"))
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Поведение заблокированного/удалённого пользователя
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_blocked_user_returns_403(client, db_session, fake_redis):
    user = await _make_user(
        db_session,
        phone="79990001013",
        referral_code="BLKLOG01",
        status=User.STATUS_BLOCKED,
        blocked_reason="fraud",
    )
    _put_otp(fake_redis, user.phone)

    r = await client.post(
        "/api/v1/auth/login/",
        json={"phone": user.phone, "code": CODE, "password": PASSWORD},
    )
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert detail["message"] == "Аккаунт заблокирован"
    assert detail["reason"] == "fraud"


@pytest.mark.asyncio
async def test_login_active_user_ok(client, db_session, fake_redis):
    user = await _make_user(db_session, phone="79990001014", referral_code="ACTLOG01")
    _put_otp(fake_redis, user.phone)

    r = await client.post(
        "/api/v1/auth/login/",
        json={"phone": user.phone, "code": CODE, "password": PASSWORD},
    )
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]


@pytest.mark.asyncio
async def test_blocked_user_jwt_rejected_with_403(client, db_session):
    user = await _make_user(
        db_session, phone="79990001015", referral_code="BLKJWT01", status=User.STATUS_BLOCKED
    )
    headers = {"Authorization": f"Bearer {make_user_jwt(user.id)}"}

    r = await client.get("/api/v1/referrals/me/balance/", headers=headers)
    assert r.status_code == 403
    assert r.json()["detail"] == "Аккаунт заблокирован"


@pytest.mark.asyncio
async def test_deleted_user_jwt_rejected_with_403(client, db_session):
    user = await _make_user(
        db_session, phone=None, referral_code="DELJWT01", status=User.STATUS_DELETED
    )
    headers = {"Authorization": f"Bearer {make_user_jwt(user.id)}"}

    r = await client.get("/api/v1/referrals/me/balance/", headers=headers)
    assert r.status_code == 403
    assert r.json()["detail"] == "Аккаунт удалён"


# ---------------------------------------------------------------------------
# Запрос SMS-кода: сохранение OTP и дневной лимит
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_code_stores_otp_and_enforces_daily_limit(client, db_session, fake_redis):
    await SettingsService(db_session).update({"sms_daily_limit_per_user": 2})
    phone = "79990001016"

    r1 = await client.post("/api/v1/auth/request-code/", json={"phone": phone})
    assert r1.status_code == 202, r1.text
    saved = json.loads(fake_redis.store[f"otp:{phone}"])
    assert len(saved["code"]) == 6 and saved["code"].isdigit()

    r2 = await client.post("/api/v1/auth/request-code/", json={"phone": phone})
    assert r2.status_code == 202

    r3 = await client.post("/api/v1/auth/request-code/", json={"phone": phone})
    assert r3.status_code == 429
