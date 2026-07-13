"""Спринт 2, БЛОК 5: фоновые задачи — процессинг созревших начислений
и отправка SMS из очереди с дневным лимитом."""

import json
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from passlib.context import CryptContext
from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.sms_notification import SMSNotification
from app.models.users.entities import User
from app.models.users.referral import ReferralAccrual
from app.services.notification_service import NotificationService
from app.services.settings_service import SettingsService
from app.tasks.accrual_job import process_matured_accruals_job
from app.tasks.sms_job import send_pending_sms_job

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
PASSWORD_HASH = pwd.hash("Password1")
CODE = "123456"


class StubSMS:
    """Подменный SMSC-клиент: копит отправленное или падает по требованию."""

    def __init__(self, fail: bool = False):
        self.sent: list[tuple[str, str]] = []
        self.fail = fail

    async def send_message(self, phone: str, text: str):
        if self.fail:
            raise RuntimeError("smsc down")
        self.sent.append((phone, text))


def _phone() -> str:
    return f"7998{uuid.uuid4().int % 10**7:07d}"


async def _make_user(db_session, *, phone=None, pending=Decimal("0")) -> User:
    user = User(
        email=None,
        phone=phone if phone is not None else _phone(),
        password_hash=PASSWORD_HASH,
        referral_code=uuid.uuid4().hex[:12].upper(),
        pending_balance=pending,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _make_accrual(db_session, *, user_id, source_id, amount, available_at) -> ReferralAccrual:
    accrual = ReferralAccrual(
        user_id=user_id,
        source_user_id=source_id,
        level=1,
        percent=Decimal("0.03"),
        base_amount=Decimal("1000"),
        amount=amount,
        status=ReferralAccrual.STATUS_PENDING,
        available_at=available_at,
    )
    db_session.add(accrual)
    await db_session.commit()
    await db_session.refresh(accrual)
    return accrual


# ---------------------------------------------------------------------------
# Задача процессинга созревших начислений
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accrual_job_credits_matured(db_session):
    recipient = await _make_user(db_session, pending=Decimal("30.00"))
    source = await _make_user(db_session)
    accrual = await _make_accrual(
        db_session,
        user_id=recipient.id,
        source_id=source.id,
        amount=Decimal("30.00"),
        available_at=datetime.utcnow() - timedelta(days=1),
    )

    count = await process_matured_accruals_job(session=db_session)
    assert count == 1

    await db_session.refresh(recipient)
    await db_session.refresh(accrual)
    assert recipient.balance == Decimal("30.00")
    assert recipient.pending_balance == Decimal("0.00")
    assert accrual.status == ReferralAccrual.STATUS_CREDITED
    assert accrual.credited_at is not None

    # SMS-уведомление поставлено в очередь
    row = await db_session.execute(
        select(SMSNotification).where(SMSNotification.user_id == recipient.id)
    )
    notification = row.scalar_one()
    assert notification.template == "bonus_accrued"
    assert notification.text == "Начислено 30.00 бонусов"
    assert notification.status == SMSNotification.STATUS_PENDING

    # Системная запись в аудите
    row = await db_session.execute(
        select(AuditLog).where(AuditLog.action == AuditLog.ACTION_BONUS_ACCRUAL_AUTO)
    )
    entry = row.scalars().first()
    assert entry is not None
    assert entry.performed_by_type == AuditLog.BY_SYSTEM


@pytest.mark.asyncio
async def test_accrual_job_skips_unmatured(db_session):
    recipient = await _make_user(db_session, pending=Decimal("30.00"))
    source = await _make_user(db_session)
    await _make_accrual(
        db_session,
        user_id=recipient.id,
        source_id=source.id,
        amount=Decimal("30.00"),
        available_at=datetime.utcnow() + timedelta(days=14),
    )

    count = await process_matured_accruals_job(session=db_session)
    assert count == 0

    await db_session.refresh(recipient)
    assert recipient.balance == Decimal("0.00")
    assert recipient.pending_balance == Decimal("30.00")


# ---------------------------------------------------------------------------
# Задача отправки SMS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sms_job_sends_pending_and_respects_daily_limit(db_session):
    await SettingsService(db_session).update({"sms_daily_limit_per_user": 2})
    user = await _make_user(db_session)
    notifications = NotificationService(db_session)
    for amount in ("10.00", "20.00", "30.00"):
        await notifications.send(user.id, "bonus_accrued", {"amount": amount})
    await db_session.commit()

    stub = StubSMS()
    stats = await send_pending_sms_job(session=db_session, sms_service=stub)
    assert stats == {"sent": 2, "failed": 0, "deferred": 1}
    assert len(stub.sent) == 2
    assert stub.sent[0] == (user.phone, "Начислено 10.00 бонусов")

    rows = await db_session.execute(
        select(SMSNotification)
        .where(SMSNotification.user_id == user.id)
        .order_by(SMSNotification.id)
    )
    statuses = [n.status for n in rows.scalars().all()]
    assert statuses == [
        SMSNotification.STATUS_SENT,
        SMSNotification.STATUS_SENT,
        SMSNotification.STATUS_PENDING,  # отложено до следующего окна
    ]

    # Повторный запуск в тот же день ничего не шлёт — лимит исчерпан.
    stats = await send_pending_sms_job(session=db_session, sms_service=stub)
    assert stats == {"sent": 0, "failed": 0, "deferred": 1}


@pytest.mark.asyncio
async def test_sms_job_marks_failed_on_provider_error(db_session):
    user = await _make_user(db_session)
    await NotificationService(db_session).send(
        user.id, "bonus_accrued", {"amount": "5.00"}
    )
    await db_session.commit()

    stats = await send_pending_sms_job(session=db_session, sms_service=StubSMS(fail=True))
    assert stats == {"sent": 0, "failed": 1, "deferred": 0}

    row = await db_session.execute(
        select(SMSNotification).where(SMSNotification.user_id == user.id)
    )
    assert row.scalar_one().status == SMSNotification.STATUS_FAILED


@pytest.mark.asyncio
async def test_notification_service_skips_user_without_phone(db_session):
    user = await _make_user(db_session)
    user.phone = None
    await db_session.commit()

    created = await NotificationService(db_session).send(
        user.id, "bonus_accrued", {"amount": "5.00"}
    )
    assert created is None


# ---------------------------------------------------------------------------
# Welcome-SMS при регистрации
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registration_enqueues_welcome_sms(client, db_session, fake_redis):
    referrer = await _make_user(db_session)
    phone = _phone()
    fake_redis.store[f"otp:{phone}"] = json.dumps({"code": CODE, "attempts": 0})

    r = await client.post(
        "/api/v1/auth/register/",
        json={
            "phone": phone,
            "code": CODE,
            "email": f"w{phone}@example.com",
            "password": "Password1",
            "first_name": "Иван",
            "referral_code": referrer.referral_code,
        },
    )
    assert r.status_code == 201, r.text
    new_user = r.json()["user"]

    row = await db_session.execute(
        select(SMSNotification).where(SMSNotification.user_id == new_user["id"])
    )
    notification = row.scalar_one()
    assert notification.template == "registration_welcome"
    assert new_user["referral_code"] in notification.text
    assert notification.status == SMSNotification.STATUS_PENDING
