"""Спринт 4, БЛОК 8: партнёры и заявки на сертификаты — создание без
списания, списание при complete, отмена без возврата, история статусов,
SMS, доступы."""

import io
import uuid
from decimal import Decimal

import pytest
from passlib.context import CryptContext
from sqlalchemy import select

from app.main import app
from app.models.audit_log import AuditLog
from app.models.certificates import CertificateRequest, CertificateStatusEvent
from app.models.partners import Partner
from app.models.sms_notification import SMSNotification
from app.models.tables.chat import Chat
from app.models.tables.message import Message
from app.models.tables.support_agent import SupportAgent
from app.models.users.entities import User
from tests.conftest import make_support_jwt, make_user_jwt

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
PASSWORD_HASH = pwd.hash("Password1")


class FakeMinio:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_object(self, bucket, key, stream, size, content_type=None):
        self.objects[f"{bucket}/{key}"] = stream.read()

    def presigned_get_object(self, bucket, key):
        return f"http://fake-minio/{bucket}/{key}"


@pytest.fixture
def fake_minio():
    fake = FakeMinio()
    app.state.minio = fake
    yield fake
    del app.state.minio


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_user(db_session, *, balance="1000.00") -> User:
    user = User(
        phone=f"7998{uuid.uuid4().int % 10**7:07d}",
        password_hash=PASSWORD_HASH,
        referral_code=uuid.uuid4().hex[:12].upper(),
        balance=Decimal(balance),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _make_manager(db_session, permissions: list[str]) -> SupportAgent:
    agent = SupportAgent(
        login=f"mgr-{uuid.uuid4().hex[:8]}",
        password_hash=PASSWORD_HASH,
        display_name="Менеджер Сертификатов",
        role=SupportAgent.ROLE_MANAGER,
        permissions=permissions,
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


async def _make_partner(db_session, **overrides) -> Partner:
    fields = {
        "name": f"Партнёр {uuid.uuid4().hex[:6]}",
        "min_exchange": Decimal("100.00"),
        "max_exchange": Decimal("5000.00"),
        "exchange_step": Decimal("100.00"),
        "status": Partner.STATUS_ACTIVE,
    }
    fields.update(overrides)
    partner = Partner(**fields)
    db_session.add(partner)
    await db_session.commit()
    await db_session.refresh(partner)
    return partner


async def _create_request(client, user, partner, amount="500.00") -> dict:
    resp = await client.post(
        "/api/v1/certificates/",
        json={"partner_id": partner.id, "amount": amount},
        headers=_headers(make_user_jwt(user.id)),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _complete(client, manager, certificate_id):
    return await client.post(
        f"/api/v1/support/certificates/{certificate_id}/complete/",
        files={"certificate_file": ("cert.pdf", io.BytesIO(b"PDF"), "application/pdf")},
        headers=_headers(make_support_jwt(manager.id)),
    )


@pytest.mark.asyncio
async def test_admin_creates_partner_and_user_sees_it(client, db_session, admin_headers):
    resp = await client.post(
        "/api/v1/admin/partners/",
        data={"name": "Летуаль", "min_exchange": "200.00", "max_exchange": "3000.00"},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    partner_id = resp.json()["id"]
    assert resp.json()["status"] == "active"

    audit = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == AuditLog.ACTION_PARTNER_CREATE,
            AuditLog.target_id == str(partner_id),
        )
    )
    assert audit.scalar_one().new_value["name"] == "Летуаль"

    user = await _make_user(db_session)
    resp = await client.get("/api/v1/partners/", headers=_headers(make_user_jwt(user.id)))
    assert resp.status_code == 200
    assert partner_id in [p["id"] for p in resp.json()]

    # Деактивация убирает партнёра из пользовательского списка
    resp = await client.patch(
        f"/api/v1/admin/partners/{partner_id}/",
        data={"status": "inactive"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    resp = await client.get("/api/v1/partners/", headers=_headers(make_user_jwt(user.id)))
    assert partner_id not in [p["id"] for p in resp.json()]


@pytest.mark.asyncio
async def test_create_request_does_not_debit_and_opens_bonus_chat(client, db_session):
    user = await _make_user(db_session, balance="1000.00")
    partner = await _make_partner(db_session)

    body = await _create_request(client, user, partner, "500.00")
    assert body["status"] == "new"

    await db_session.refresh(user)
    assert user.balance == Decimal("1000.00")

    chat = (
        await db_session.execute(
            select(Chat).where(Chat.owner_user_id == user.id, Chat.type == Chat.TYPE_BONUS)
        )
    ).scalar_one()
    assert str(chat.id) == body["bonus_chat_id"]

    messages = (
        await db_session.execute(select(Message).where(Message.chat_id == chat.id))
    ).scalars().all()
    assert any(partner.name in (m.body or "") for m in messages)

    # Повторная заявка переиспользует единственный bonus-чат пользователя
    body2 = await _create_request(client, user, partner, "300.00")
    assert body2["bonus_chat_id"] == body["bonus_chat_id"]


@pytest.mark.asyncio
async def test_create_request_validations(client, db_session):
    user = await _make_user(db_session, balance="150.00")
    partner = await _make_partner(
        db_session, min_exchange=Decimal("100.00"), max_exchange=Decimal("200.00")
    )
    headers = _headers(make_user_jwt(user.id))

    # Недостаточно бонусов
    resp = await client.post(
        "/api/v1/certificates/",
        json={"partner_id": partner.id, "amount": "500.00"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "insufficient" in resp.json()["detail"]

    # Ниже минимума партнёра
    resp = await client.post(
        "/api/v1/certificates/",
        json={"partner_id": partner.id, "amount": "50.00"},
        headers=headers,
    )
    assert resp.status_code == 400

    # Неактивный партнёр
    inactive = await _make_partner(db_session, status=Partner.STATUS_INACTIVE)
    resp = await client.post(
        "/api/v1/certificates/",
        json={"partner_id": inactive.id, "amount": "100.00"},
        headers=headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_status_change_keeps_balance(client, db_session):
    user = await _make_user(db_session, balance="1000.00")
    partner = await _make_partner(db_session)
    manager = await _make_manager(db_session, [SupportAgent.PERMISSION_CERTIFICATES])
    body = await _create_request(client, user, partner, "500.00")

    resp = await client.patch(
        f"/api/v1/support/certificates/{body['id']}/status/",
        json={"new_status": "in_progress"},
        headers=_headers(make_support_jwt(manager.id)),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "in_progress"
    assert resp.json()["assigned_manager_id"] == manager.id

    await db_session.refresh(user)
    assert user.balance == Decimal("1000.00")

    # completed через смену статуса запрещён — только через complete
    resp = await client.patch(
        f"/api/v1/support/certificates/{body['id']}/status/",
        json={"new_status": "completed"},
        headers=_headers(make_support_jwt(manager.id)),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_complete_debits_bonuses_and_stores_file(client, db_session, fake_minio):
    user = await _make_user(db_session, balance="1000.00")
    partner = await _make_partner(db_session)
    manager = await _make_manager(db_session, [SupportAgent.PERMISSION_CERTIFICATES])
    body = await _create_request(client, user, partner, "500.00")

    resp = await _complete(client, manager, body["id"])
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "completed"
    assert data["certificate_file_key"]

    await db_session.refresh(user)
    assert user.balance == Decimal("500.00")
    assert f"chat-files/{data['certificate_file_key']}" in list(fake_minio.objects)

    # SMS о завершении в очереди
    sms = (
        await db_session.execute(
            select(SMSNotification).where(
                SMSNotification.user_id == user.id,
                SMSNotification.template == "certificate_completed",
            )
        )
    ).scalar_one()
    assert partner.name in sms.text

    audit = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == AuditLog.ACTION_CERTIFICATE_COMPLETE,
            AuditLog.target_id == body["id"],
        )
    )
    assert audit.scalar_one().performed_by_id == manager.id

    # Скачивание файла менеджером
    resp = await client.post(
        f"/api/v1/support/certificates/{body['id']}/download/",
        headers=_headers(make_support_jwt(manager.id)),
    )
    assert resp.status_code == 200
    assert data["certificate_file_key"] in resp.json()["url"]


@pytest.mark.asyncio
async def test_cancel_does_not_refund_debited_bonuses(client, db_session, fake_minio):
    user = await _make_user(db_session, balance="1000.00")
    partner = await _make_partner(db_session)
    manager = await _make_manager(db_session, [SupportAgent.PERMISSION_CERTIFICATES])
    body = await _create_request(client, user, partner, "500.00")

    assert (await _complete(client, manager, body["id"])).status_code == 200

    resp = await client.post(
        f"/api/v1/support/certificates/{body['id']}/cancel/",
        json={"reason": "партнёр не подтвердил"},
        headers=_headers(make_support_jwt(manager.id)),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cancelled"
    assert resp.json()["cancel_reason"] == "партнёр не подтвердил"

    # Бонусы остаются списанными
    await db_session.refresh(user)
    assert user.balance == Decimal("500.00")

    sms = (
        await db_session.execute(
            select(SMSNotification).where(
                SMSNotification.user_id == user.id,
                SMSNotification.template == "certificate_cancelled",
            )
        )
    ).scalar_one()
    assert "партнёр не подтвердил" in sms.text


@pytest.mark.asyncio
async def test_user_sees_only_own_requests_with_history(client, db_session):
    user = await _make_user(db_session)
    stranger = await _make_user(db_session)
    partner = await _make_partner(db_session)
    manager = await _make_manager(db_session, [SupportAgent.PERMISSION_CERTIFICATES])
    body = await _create_request(client, user, partner, "300.00")
    await _create_request(client, stranger, partner, "200.00")

    await client.patch(
        f"/api/v1/support/certificates/{body['id']}/status/",
        json={"new_status": "confirming", "comment": "проверяем"},
        headers=_headers(make_support_jwt(manager.id)),
    )

    resp = await client.get(
        "/api/v1/certificates/", headers=_headers(make_user_jwt(user.id))
    )
    assert resp.status_code == 200
    assert [c["id"] for c in resp.json()] == [body["id"]]

    detail = await client.get(
        f"/api/v1/certificates/{body['id']}/", headers=_headers(make_user_jwt(user.id))
    )
    assert detail.status_code == 200
    events = detail.json()["status_events"]
    assert [(e["old_status"], e["new_status"]) for e in events] == [("new", "confirming")]

    resp = await client.get(
        f"/api/v1/certificates/{body['id']}/", headers=_headers(make_user_jwt(stranger.id))
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_certificates_permission_required(client, db_session):
    user = await _make_user(db_session)
    partner = await _make_partner(db_session)
    manager = await _make_manager(db_session, [SupportAgent.PERMISSION_CHATS])
    body = await _create_request(client, user, partner, "300.00")

    resp = await client.get(
        "/api/v1/support/certificates/",
        headers=_headers(make_support_jwt(manager.id)),
    )
    assert resp.status_code == 403

    resp = await client.patch(
        f"/api/v1/support/certificates/{body['id']}/status/",
        json={"new_status": "confirming"},
        headers=_headers(make_support_jwt(manager.id)),
    )
    assert resp.status_code == 403
