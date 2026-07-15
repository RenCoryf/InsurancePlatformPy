"""Спринт 3, БЛОК 6: заявки — создание пользователем/менеджером,
insurance-чат с системными сообщениями, смена статуса (events, SMS, audit)."""

import uuid

import pytest
from passlib.context import CryptContext
from sqlalchemy import select

from app.models.applications import Application, ApplicationStatusEvent
from app.models.audit_log import AuditLog
from app.models.sms_notification import SMSNotification
from app.models.tables.chat import Chat
from app.models.tables.message import Message
from app.models.tables.support_agent import SupportAgent
from app.models.users.entities import User
from tests.conftest import make_support_jwt, make_user_jwt

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
PASSWORD_HASH = pwd.hash("Password1")

_phone_seq = {"n": 0}


def _phone() -> str:
    _phone_seq["n"] += 1
    return f"7998{uuid.uuid4().int % 10**7:07d}"


async def _make_user(db_session) -> User:
    user = User(
        phone=_phone(),
        password_hash=PASSWORD_HASH,
        referral_code=uuid.uuid4().hex[:12].upper(),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _make_manager(db_session, permissions: list[str]) -> SupportAgent:
    agent = SupportAgent(
        login=f"mgr-{uuid.uuid4().hex[:8]}",
        password_hash=PASSWORD_HASH,
        display_name="Иван Менеджеров",
        role=SupportAgent.ROLE_MANAGER,
        permissions=permissions,
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _chat_messages(db_session, chat_id) -> list[Message]:
    rows = await db_session.execute(
        select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)
    )
    return list(rows.scalars().all())


@pytest.mark.asyncio
async def test_user_creates_application_with_chat_and_system_message(client, db_session):
    user = await _make_user(db_session)

    resp = await client.post(
        "/api/v1/applications/",
        json={"product": "osago"},
        headers=_headers(make_user_jwt(user.id)),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "new"
    assert body["created_by"] == "user"
    assert body["chat_id"] is not None

    chat = await db_session.get(Chat, uuid.UUID(body["chat_id"]))
    assert chat.type == "insurance"
    assert chat.owner_user_id == user.id

    messages = await _chat_messages(db_session, chat.id)
    assert len(messages) == 1
    assert messages[0].sender_subject_type == "system"
    assert "ОСАГО" in messages[0].body


@pytest.mark.asyncio
async def test_user_can_have_multiple_insurance_chats(client, db_session):
    user = await _make_user(db_session)
    headers = _headers(make_user_jwt(user.id))

    for product in ("osago", "kasko"):
        resp = await client.post("/api/v1/applications/", json={"product": product}, headers=headers)
        assert resp.status_code == 201, resp.text

    resp = await client.get("/api/v1/applications/", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_unknown_product_rejected(client, db_session):
    user = await _make_user(db_session)
    resp = await client.post(
        "/api/v1/applications/",
        json={"product": "travel"},
        headers=_headers(make_user_jwt(user.id)),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_foreign_application_details_forbidden(client, db_session):
    owner = await _make_user(db_session)
    stranger = await _make_user(db_session)
    resp = await client.post(
        "/api/v1/applications/",
        json={"product": "pds"},
        headers=_headers(make_user_jwt(owner.id)),
    )
    app_id = resp.json()["id"]

    resp = await client.get(
        f"/api/v1/applications/{app_id}/", headers=_headers(make_user_jwt(stranger.id))
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_manager_creates_application_for_user(client, db_session):
    user = await _make_user(db_session)
    manager = await _make_manager(db_session, [SupportAgent.PERMISSION_APPLICATIONS])

    resp = await client.post(
        "/api/v1/support/applications/",
        json={"user_id": user.id, "product": "kasko", "comment": "по звонку"},
        headers=_headers(make_support_jwt(manager.id)),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["created_by"] == "manager"
    assert body["assigned_manager_id"] == manager.id
    assert body["manager_comment"] == "по звонку"

    messages = await _chat_messages(db_session, uuid.UUID(body["chat_id"]))
    assert "менеджером Иван Менеджеров" in messages[0].body

    audit = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == AuditLog.ACTION_APPLICATION_CREATE,
            AuditLog.target_id == body["id"],
        )
    )
    assert audit.scalar_one().performed_by_id == manager.id


@pytest.mark.asyncio
async def test_manager_without_permission_forbidden(client, db_session):
    user = await _make_user(db_session)
    manager = await _make_manager(db_session, [SupportAgent.PERMISSION_CHATS])

    resp = await client.post(
        "/api/v1/support/applications/",
        json={"user_id": user.id, "product": "osago"},
        headers=_headers(make_support_jwt(manager.id)),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_status_change_writes_event_sms_audit_and_chat_message(client, db_session):
    user = await _make_user(db_session)
    manager = await _make_manager(db_session, [SupportAgent.PERMISSION_APPLICATIONS])
    mgr_headers = _headers(make_support_jwt(manager.id))

    resp = await client.post(
        "/api/v1/applications/",
        json={"product": "osago"},
        headers=_headers(make_user_jwt(user.id)),
    )
    app_id = resp.json()["id"]
    chat_id = uuid.UUID(resp.json()["chat_id"])

    resp = await client.patch(
        f"/api/v1/support/applications/{app_id}/status/",
        json={"new_status": "in_progress", "comment": "взял в работу"},
        headers=mgr_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "in_progress"

    events = await db_session.execute(
        select(ApplicationStatusEvent).where(
            ApplicationStatusEvent.application_id == uuid.UUID(app_id)
        )
    )
    event = events.scalar_one()
    assert (event.old_status, event.new_status) == ("new", "in_progress")
    assert event.changed_by_id == manager.id

    # created_at обоих сообщений совпадает (now() в Postgres — время
    # транзакции), поэтому проверяем состав, а не порядок.
    bodies = [m.body for m in await _chat_messages(db_session, chat_id)]
    assert len(bodies) == 2
    assert "Статус изменён: new → in_progress" in bodies

    sms = await db_session.execute(
        select(SMSNotification).where(
            SMSNotification.user_id == user.id,
            SMSNotification.template == "application_status_changed",
        )
    )
    assert sms.scalar_one().status == SMSNotification.STATUS_PENDING

    audit = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == AuditLog.ACTION_APPLICATION_STATUS_CHANGE,
            AuditLog.target_id == app_id,
        )
    )
    assert audit.scalar_one().new_value == {"status": "in_progress"}

    # История статусов видна в деталях
    detail = await client.get(f"/api/v1/support/applications/{app_id}/", headers=mgr_headers)
    assert len(detail.json()["status_events"]) == 1

    # Повторная смена на тот же статус — ошибка
    resp = await client.patch(
        f"/api/v1/support/applications/{app_id}/status/",
        json={"new_status": "in_progress"},
        headers=mgr_headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_support_list_filters(client, db_session):
    user = await _make_user(db_session)
    manager = await _make_manager(db_session, [SupportAgent.PERMISSION_APPLICATIONS])
    mgr_headers = _headers(make_support_jwt(manager.id))
    user_headers = _headers(make_user_jwt(user.id))

    await client.post("/api/v1/applications/", json={"product": "osago"}, headers=user_headers)
    await client.post("/api/v1/applications/", json={"product": "legal"}, headers=user_headers)

    resp = await client.get(
        "/api/v1/support/applications/",
        params={"user_id": user.id, "product": "legal"},
        headers=mgr_headers,
    )
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["product"] == "legal"
