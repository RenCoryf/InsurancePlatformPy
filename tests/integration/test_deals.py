"""Спринт 3, БЛОК 7: сделки — создание, accrual_date, начисление бонусов
по 4 уровням при policy_issued, отмена начислений при отмене сделки,
смена суммы только админом."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from passlib.context import CryptContext
from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.models.deals import Deal, DealStatusEvent
from app.models.tables.support_agent import SupportAgent
from app.models.users.entities import User
from app.models.users.referral import ReferralAccrual
from tests.conftest import make_support_jwt, make_user_jwt

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
PASSWORD_HASH = pwd.hash("Password1")

_phone_seq = {"n": 0}

POLICY_DATE = date(2026, 7, 14)


def _phone() -> str:
    _phone_seq["n"] += 1
    return f"7997{uuid.uuid4().int % 10**7:07d}"


async def _make_user(db_session, *, referrer_id=None) -> User:
    user = User(
        phone=_phone(),
        password_hash=PASSWORD_HASH,
        referral_code=uuid.uuid4().hex[:12].upper(),
        referrer_id=referrer_id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _make_chain(db_session) -> list[User]:
    """owner → l4 → l3 → l2 → l1 → source (l1 — первый уровень аплайна source)."""
    chain = [await _make_user(db_session)]
    for _ in range(5):
        chain.append(await _make_user(db_session, referrer_id=chain[-1].id))
    return chain


async def _make_manager(db_session, permissions: list[str], role=SupportAgent.ROLE_MANAGER) -> SupportAgent:
    agent = SupportAgent(
        login=f"mgr-{uuid.uuid4().hex[:8]}",
        password_hash=PASSWORD_HASH,
        display_name="Менеджер Сделок",
        role=role,
        permissions=permissions,
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_deal(client, manager, user, amount="10000.00") -> dict:
    resp = await client.post(
        "/api/v1/support/deals/",
        json={
            "user_id": user.id,
            "product": "kasko",
            "policy_amount": amount,
            "policy_date": str(POLICY_DATE),
        },
        headers=_headers(make_support_jwt(manager.id)),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _pending_balances(db_session, users: list[User]) -> list[Decimal]:
    out = []
    for u in users:
        await db_session.refresh(u)
        out.append(u.pending_balance)
    return out


@pytest.mark.asyncio
async def test_create_deal_sets_accrual_date_from_settings(client, db_session):
    user = await _make_user(db_session)
    manager = await _make_manager(db_session, [SupportAgent.PERMISSION_DEALS])

    body = await _create_deal(client, manager, user)
    assert body["status"] == "new"
    assert body["assigned_manager_id"] == manager.id
    # Дефолт настроек: bonus_accrual_delay_days = 15
    assert body["accrual_date"] == str(POLICY_DATE + timedelta(days=15))

    audit = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == AuditLog.ACTION_DEAL_CREATE,
            AuditLog.target_id == body["id"],
        )
    )
    assert audit.scalar_one().performed_by_id == manager.id


@pytest.mark.asyncio
async def test_policy_issued_accrues_bonuses_to_four_levels(client, db_session):
    owner, l4, l3, l2, l1, source = await _make_chain(db_session)
    manager = await _make_manager(db_session, [SupportAgent.PERMISSION_DEALS])
    body = await _create_deal(client, manager, source)

    resp = await client.patch(
        f"/api/v1/support/deals/{body['id']}/status/",
        json={"new_status": "policy_issued"},
        headers=_headers(make_support_jwt(manager.id)),
    )
    assert resp.status_code == 200, resp.text

    # 3% / 3% / 2% / 1% от 10000 по уровням 1..4
    assert await _pending_balances(db_session, [l1, l2, l3, l4]) == [
        Decimal("300.00"), Decimal("300.00"), Decimal("200.00"), Decimal("100.00"),
    ]

    accruals = await db_session.execute(
        select(ReferralAccrual).where(ReferralAccrual.deal_id == uuid.UUID(body["id"]))
    )
    accruals = list(accruals.scalars().all())
    assert len(accruals) == 4
    assert all(a.status == ReferralAccrual.STATUS_PENDING for a in accruals)
    # Доступность бонусов — accrual_date сделки
    assert all(a.available_at.date() == POLICY_DATE + timedelta(days=15) for a in accruals)


@pytest.mark.asyncio
async def test_rejecting_issued_deal_cancels_accruals(client, db_session):
    owner, l4, l3, l2, l1, source = await _make_chain(db_session)
    manager = await _make_manager(db_session, [SupportAgent.PERMISSION_DEALS])
    body = await _create_deal(client, manager, source)
    mgr_headers = _headers(make_support_jwt(manager.id))

    await client.patch(
        f"/api/v1/support/deals/{body['id']}/status/",
        json={"new_status": "policy_issued"},
        headers=mgr_headers,
    )
    resp = await client.patch(
        f"/api/v1/support/deals/{body['id']}/status/",
        json={"new_status": "rejected", "comment": "клиент отказался"},
        headers=mgr_headers,
    )
    assert resp.status_code == 200, resp.text

    assert await _pending_balances(db_session, [l1, l2, l3, l4]) == [Decimal("0.00")] * 4

    accruals = await db_session.execute(
        select(ReferralAccrual).where(ReferralAccrual.deal_id == uuid.UUID(body["id"]))
    )
    assert all(
        a.status == ReferralAccrual.STATUS_CANCELLED for a in accruals.scalars().all()
    )

    events = await db_session.execute(
        select(DealStatusEvent).where(DealStatusEvent.deal_id == uuid.UUID(body["id"]))
    )
    transitions = [(e.old_status, e.new_status) for e in events.scalars().all()]
    assert transitions == [("new", "policy_issued"), ("policy_issued", "rejected")]


@pytest.mark.asyncio
async def test_user_sees_own_deals_with_history(client, db_session):
    user = await _make_user(db_session)
    stranger = await _make_user(db_session)
    manager = await _make_manager(db_session, [SupportAgent.PERMISSION_DEALS])
    body = await _create_deal(client, manager, user)

    await client.patch(
        f"/api/v1/support/deals/{body['id']}/status/",
        json={"new_status": "in_progress"},
        headers=_headers(make_support_jwt(manager.id)),
    )

    resp = await client.get("/api/v1/deals/", headers=_headers(make_user_jwt(user.id)))
    assert resp.status_code == 200
    assert [d["id"] for d in resp.json()] == [body["id"]]

    detail = await client.get(
        f"/api/v1/deals/{body['id']}/", headers=_headers(make_user_jwt(user.id))
    )
    assert detail.status_code == 200
    assert len(detail.json()["status_events"]) == 1

    resp = await client.get(
        f"/api/v1/deals/{body['id']}/", headers=_headers(make_user_jwt(stranger.id))
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_amount_change_is_admin_only_and_audited(client, db_session):
    user = await _make_user(db_session)
    manager = await _make_manager(db_session, [SupportAgent.PERMISSION_DEALS])
    admin = await _make_manager(db_session, [], role=SupportAgent.ROLE_ADMIN)
    body = await _create_deal(client, manager, user)

    resp = await client.patch(
        f"/api/v1/support/deals/{body['id']}/amount/",
        json={"new_amount": "12000.00", "reason": "перерасчёт"},
        headers=_headers(make_support_jwt(manager.id)),
    )
    assert resp.status_code == 403

    resp = await client.patch(
        f"/api/v1/support/deals/{body['id']}/amount/",
        json={"new_amount": "12000.00", "reason": "перерасчёт"},
        headers=_headers(make_support_jwt(admin.id)),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["policy_amount"] == "12000.00"

    audit = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == AuditLog.ACTION_DEAL_AMOUNT_CHANGE,
            AuditLog.target_id == body["id"],
        )
    )
    entry = audit.scalar_one()
    assert entry.old_value == {"amount": "10000.00"}
    assert entry.comment == "перерасчёт"


@pytest.mark.asyncio
async def test_deal_permission_required(client, db_session):
    user = await _make_user(db_session)
    manager = await _make_manager(db_session, [SupportAgent.PERMISSION_CHATS])
    resp = await client.post(
        "/api/v1/support/deals/",
        json={
            "user_id": user.id,
            "product": "osago",
            "policy_amount": "5000.00",
            "policy_date": str(POLICY_DATE),
        },
        headers=_headers(make_support_jwt(manager.id)),
    )
    assert resp.status_code == 403
