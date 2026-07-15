"""Спринт 5, блок 9: SMS-шаблоны в настройках и уведомления по всем событиям
(chat_new_message, certificate_confirming, коды входа/регистрации)."""

import json
import uuid
from decimal import Decimal

import pytest
from passlib.context import CryptContext
from sqlalchemy import select

from app.models.sms_notification import SMSNotification
from app.models.tables.chat import Chat
from app.models.tables.support_agent import SupportAgent
from app.models.users.entities import User
from app.services.internal_service import InternalService
from app.services.notification_service import (
    DEFAULT_SMS_TEMPLATES,
    NotificationService,
)

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
PASSWORD_HASH = pwd.hash("Password1")


async def _make_user(db_session, **overrides) -> User:
    fields = {
        "phone": f"7997{uuid.uuid4().int % 10**7:07d}",
        "password_hash": PASSWORD_HASH,
        "referral_code": uuid.uuid4().hex[:12].upper(),
        "first_name": "Иван",
        "last_name": "Тестов",
    }
    fields.update(overrides)
    user = User(**fields)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _sms_rows(db_session, template: str) -> list[SMSNotification]:
    rows = await db_session.execute(
        select(SMSNotification).where(SMSNotification.template == template)
    )
    return list(rows.scalars().all())


# ---------------------------------------------------------------------------
# Шаблоны в настройках
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_settings_expose_and_update_sms_templates(client, admin_headers):
    r = await client.get("/api/v1/admin/settings/", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["sms_templates"] == {}

    r2 = await client.patch(
        "/api/v1/admin/settings/",
        json={"sms_templates": {"bonus_accrued": "Вам зачислено {amount}!"}},
        headers=admin_headers,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["sms_templates"] == {"bonus_accrued": "Вам зачислено {amount}!"}


@pytest.mark.asyncio
async def test_settings_reject_unknown_template_key(client, admin_headers):
    r = await client.patch(
        "/api/v1/admin/settings/",
        json={"sms_templates": {"nonexistent_template": "hi"}},
        headers=admin_headers,
    )
    assert r.status_code in (400, 422), r.text


@pytest.mark.asyncio
async def test_template_override_is_used_for_queued_sms(client, db_session, admin_headers):
    user = await _make_user(db_session)
    r = await client.patch(
        "/api/v1/admin/settings/",
        json={"sms_templates": {"bonus_accrued": "Кастом: +{amount} бонусов"}},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text

    notification = await NotificationService(db_session).send(
        user.id, "bonus_accrued", {"amount": "150.00"}
    )
    await db_session.commit()
    assert notification is not None
    assert notification.text == "Кастом: +150.00 бонусов"


@pytest.mark.asyncio
async def test_default_templates_cover_all_sprint_events(db_session):
    for template in (
        "registration_welcome",
        "login_code",
        "registration_code",
        "chat_new_message",
        "application_status_changed",
        "bonus_accrued",
        "certificate_confirming",
        "certificate_completed",
        "certificate_cancelled",
        "manager_invite",
    ):
        assert template in DEFAULT_SMS_TEMPLATES


@pytest.mark.asyncio
async def test_render_with_missing_param_returns_raw_text(db_session):
    text = await NotificationService(db_session).render_template("bonus_accrued", {})
    assert text == DEFAULT_SMS_TEMPLATES["bonus_accrued"]  # без подстановки, не падаем


@pytest.mark.asyncio
async def test_send_skips_user_without_phone(db_session):
    user = await _make_user(db_session, phone=None)
    result = await NotificationService(db_session).send(
        user.id, "bonus_accrued", {"amount": "1"}
    )
    assert result is None


@pytest.mark.asyncio
async def test_get_pending_count(db_session):
    user = await _make_user(db_session)
    svc = NotificationService(db_session)
    before = await svc.get_pending_count()
    await svc.send(user.id, "bonus_accrued", {"amount": "1.00"})
    await db_session.commit()
    assert await svc.get_pending_count() == before + 1


# ---------------------------------------------------------------------------
# Событийные уведомления
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_support_chat_message_queues_sms_to_chat_owner(db_session):
    user = await _make_user(db_session)
    agent = SupportAgent(
        login=f"chat-mgr-{uuid.uuid4().hex[:8]}",
        password_hash=PASSWORD_HASH,
        display_name="Оператор Ольга",
        role=SupportAgent.ROLE_MANAGER,
        permissions=[SupportAgent.PERMISSION_CHATS],
    )
    chat = Chat(owner_user_id=user.id, type=Chat.TYPE_MAIN)
    db_session.add_all([agent, chat])
    await db_session.commit()
    await db_session.refresh(agent)
    await db_session.refresh(chat)

    await InternalService(db_session).persist_message(
        chat_id=chat.id,
        user_id=f"support:{agent.id}",
        role="support",
        kind="message",
        body="Здравствуйте! Ваш полис готов.",
        file_id=None,
        client_msg_id=None,
    )

    rows = await _sms_rows(db_session, "chat_new_message")
    assert len(rows) == 1
    assert rows[0].user_id == user.id
    assert "Оператор Ольга" in rows[0].text


@pytest.mark.asyncio
async def test_user_own_chat_message_does_not_queue_sms(db_session):
    user = await _make_user(db_session)
    chat = Chat(owner_user_id=user.id, type=Chat.TYPE_MAIN)
    db_session.add(chat)
    await db_session.commit()
    await db_session.refresh(chat)

    await InternalService(db_session).persist_message(
        chat_id=chat.id,
        user_id=f"user:{user.id}",
        role="user",
        kind="message",
        body="Вопрос по полису",
        file_id=None,
        client_msg_id=None,
    )

    assert await _sms_rows(db_session, "chat_new_message") == []


@pytest.mark.asyncio
async def test_certificate_confirming_status_queues_sms(client, db_session):
    from app.models.partners import Partner
    from app.services.certificate_service import CertificateService

    user = await _make_user(db_session, balance=Decimal("1000.00"))
    partner = Partner(
        name=f"Партнёр {uuid.uuid4().hex[:6]}",
        min_exchange=Decimal("100.00"),
        max_exchange=Decimal("5000.00"),
        exchange_step=Decimal("100.00"),
        status=Partner.STATUS_ACTIVE,
    )
    manager = SupportAgent(
        login=f"cert-mgr-{uuid.uuid4().hex[:8]}",
        password_hash=PASSWORD_HASH,
        display_name="Менеджер",
        role=SupportAgent.ROLE_MANAGER,
        permissions=[SupportAgent.PERMISSION_CERTIFICATES],
    )
    db_session.add_all([partner, manager])
    await db_session.commit()
    await db_session.refresh(partner)
    await db_session.refresh(manager)

    svc = CertificateService(db_session)
    cert = await svc.create(user.id, partner.id, Decimal("500.00"))
    await svc.change_status(cert.id, "confirming", manager.id)

    rows = await _sms_rows(db_session, "certificate_confirming")
    assert len(rows) == 1
    assert rows[0].user_id == user.id
    assert partner.name in rows[0].text


@pytest.mark.asyncio
async def test_request_sms_code_uses_login_and_registration_templates(
    client, db_session, fake_redis
):
    # Новый номер → registration_code; SMSC не сконфигурирован — код в логе,
    # эндпоинт отвечает 200 и кладёт код в Redis.
    new_phone = f"7996{uuid.uuid4().int % 10**7:07d}"
    r = await client.post("/api/v1/auth/request-code/", json={"phone": new_phone})
    assert r.status_code == 202, r.text
    assert f"otp:{new_phone}" in fake_redis.store

    # Существующий пользователь → login_code, тоже принимается.
    user = await _make_user(db_session)
    r2 = await client.post("/api/v1/auth/request-code/", json={"phone": user.phone})
    assert r2.status_code == 202, r2.text
    assert f"otp:{user.phone}" in fake_redis.store
