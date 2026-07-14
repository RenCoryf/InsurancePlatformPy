"""Спринт 5, блок 10: разделы Users/Managers/Admins/Reports/Audit Log
админ-панели."""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from passlib.context import CryptContext
from sqlalchemy import select

from app.models.applications import Application
from app.models.audit_log import AuditLog
from app.models.deals import Deal
from app.models.partners import Partner
from app.models.sms_notification import SMSNotification
from app.models.tables.chat import Chat
from app.models.tables.support_agent import SupportAgent
from app.models.users.entities import User
from app.models.users.referral import ReferralAccrual
from app.models.certificates import CertificateRequest

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
PASSWORD_HASH = pwd.hash("Password1")


async def _make_user(db_session, **overrides) -> User:
    fields = {
        "phone": f"7995{uuid.uuid4().int % 10**7:07d}",
        "password_hash": PASSWORD_HASH,
        "referral_code": uuid.uuid4().hex[:12].upper(),
        "first_name": "Пётр",
        "last_name": "Смирнов",
    }
    fields.update(overrides)
    user = User(**fields)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _make_manager(db_session, **overrides) -> SupportAgent:
    fields = {
        "login": f"mgr-{uuid.uuid4().hex[:8]}",
        "password_hash": PASSWORD_HASH,
        "display_name": "Менеджер",
        "role": SupportAgent.ROLE_MANAGER,
        "permissions": [],
    }
    fields.update(overrides)
    agent = SupportAgent(**fields)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


async def _make_deal(
    db_session, *, user: User, manager: SupportAgent, amount="1000.00",
    product="osago", policy_date=None,
) -> Deal:
    policy_date = policy_date or date(2026, 7, 1)
    deal = Deal(
        user_id=user.id,
        product=product,
        policy_amount=Decimal(amount),
        policy_date=policy_date,
        accrual_date=policy_date + timedelta(days=15),
        status=Deal.STATUS_POLICY_ISSUED,
        assigned_manager_id=manager.id,
    )
    db_session.add(deal)
    await db_session.commit()
    await db_session.refresh(deal)
    return deal


# ---------------------------------------------------------------------------
# 10.1 Users
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_users_list_search_and_status_filter(client, db_session, admin_headers):
    marker = uuid.uuid4().hex[:8]
    target = await _make_user(db_session, first_name=f"Уникум{marker}")
    await _make_user(db_session, first_name="Другой")
    blocked = await _make_user(
        db_session, first_name=f"Уникум{marker}", status=User.STATUS_BLOCKED
    )

    r = await client.get(
        "/api/v1/admin/users/", params={"search": f"Уникум{marker}"}, headers=admin_headers
    )
    assert r.status_code == 200, r.text
    ids = {u["id"] for u in r.json()}
    assert ids == {target.id, blocked.id}

    r2 = await client.get(
        "/api/v1/admin/users/",
        params={"search": f"Уникум{marker}", "status": "blocked"},
        headers=admin_headers,
    )
    assert r2.status_code == 200
    assert [u["id"] for u in r2.json()] == [blocked.id]

    # Поиск по телефону
    r3 = await client.get(
        "/api/v1/admin/users/", params={"search": target.phone}, headers=admin_headers
    )
    assert [u["id"] for u in r3.json()] == [target.id]

    # Некорректный статус
    r4 = await client.get(
        "/api/v1/admin/users/", params={"status": "bogus"}, headers=admin_headers
    )
    assert r4.status_code == 400


@pytest.mark.asyncio
async def test_user_card_with_referrals_deals_and_audit(client, db_session, admin_headers):
    manager = await _make_manager(db_session)
    root = await _make_user(db_session, first_name="Корень")
    child = await _make_user(db_session, first_name="Ребёнок", referrer_id=root.id)
    grandchild = await _make_user(db_session, referrer_id=child.id)

    app_row = Application(
        user_id=root.id, product="kasko", status="new", created_by="user"
    )
    accrual = ReferralAccrual(
        user_id=root.id,
        source_user_id=child.id,
        level=1,
        percent=Decimal("0.03"),
        base_amount=Decimal("1000.00"),
        amount=Decimal("30.00"),
        status=ReferralAccrual.STATUS_PENDING,
        available_at=datetime.utcnow() + timedelta(days=15),
    )
    db_session.add_all([app_row, accrual])
    await db_session.commit()
    await _make_deal(db_session, user=root, manager=manager)

    # Блокировка/разблокировка, чтобы появились записи журнала по пользователю
    rb = await client.post(
        f"/api/v1/admin/users/{root.id}/block/",
        json={"reason": "request"},
        headers=admin_headers,
    )
    assert rb.status_code == 200, rb.text
    ru = await client.post(
        f"/api/v1/admin/users/{root.id}/unblock/", headers=admin_headers
    )
    assert ru.status_code == 200, ru.text

    r = await client.get(f"/api/v1/admin/users/{root.id}/", headers=admin_headers)
    assert r.status_code == 200, r.text
    card = r.json()

    assert card["id"] == root.id
    assert card["phone"] == root.phone  # админ видит полный телефон
    level1 = card["referrals"]["1"]
    level2 = card["referrals"]["2"]
    assert [m["id"] for m in level1] == [child.id]
    assert level1[0]["structure_count"] == 1  # у ребёнка один потомок
    assert [m["id"] for m in level2] == [grandchild.id]
    assert len(card["applications"]) == 1
    assert card["applications"][0]["product"] == "kasko"
    assert len(card["deals"]) == 1
    assert len(card["accruals"]) == 1
    actions = {e["action"] for e in card["audit_logs"]}
    assert {"user_block", "user_unblock"} <= actions

    r404 = await client.get("/api/v1/admin/users/999999999/", headers=admin_headers)
    assert r404.status_code == 404


@pytest.mark.asyncio
async def test_manual_bonus_credit_and_debit(client, db_session, admin_agent, admin_headers):
    user = await _make_user(db_session)

    r = await client.post(
        f"/api/v1/admin/users/{user.id}/bonus/credit/",
        json={"amount": "250.50", "reason": "компенсация"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert Decimal(str(r.json()["balance"])) == Decimal("250.50")

    r2 = await client.post(
        f"/api/v1/admin/users/{user.id}/bonus/debit/",
        json={"amount": "100.00", "reason": "корректировка"},
        headers=admin_headers,
    )
    assert r2.status_code == 200, r2.text
    assert Decimal(str(r2.json()["balance"])) == Decimal("150.50")

    # Аудит обоих действий
    rows = await db_session.execute(
        select(AuditLog).where(
            AuditLog.target_type == AuditLog.TARGET_BONUS,
            AuditLog.target_id == str(user.id),
        )
    )
    actions = [e.action for e in rows.scalars().all()]
    assert AuditLog.ACTION_BONUS_MANUAL_CREDIT in actions
    assert AuditLog.ACTION_BONUS_MANUAL_DEBIT in actions

    # SMS о ручном начислении в очереди
    sms = await db_session.execute(
        select(SMSNotification).where(
            SMSNotification.user_id == user.id,
            SMSNotification.template == "bonus_manual_credit",
        )
    )
    assert len(list(sms.scalars().all())) == 1

    # Списание больше баланса → 422
    r3 = await client.post(
        f"/api/v1/admin/users/{user.id}/bonus/debit/",
        json={"amount": "10000.00", "reason": "тест"},
        headers=admin_headers,
    )
    assert r3.status_code == 422

    # Без причины → ошибка валидации
    r4 = await client.post(
        f"/api/v1/admin/users/{user.id}/bonus/credit/",
        json={"amount": "10.00", "reason": ""},
        headers=admin_headers,
    )
    assert r4.status_code in (400, 422)


@pytest.mark.asyncio
async def test_users_csv_export(client, db_session, admin_headers):
    user = await _make_user(db_session)
    r = await client.get("/api/v1/admin/users/export/", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("id,first_name,last_name,phone,email,status")
    assert any(f"{user.id}," in line and user.phone in line for line in lines[1:])


# ---------------------------------------------------------------------------
# 10.2 Managers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_managers_list_returns_only_managers(client, db_session, admin_agent, admin_headers):
    manager = await _make_manager(db_session)
    r = await client.get("/api/v1/admin/managers/", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {a["id"] for a in body}
    assert manager.id in ids
    assert admin_agent.id not in ids  # админы в списке менеджеров не выводятся
    assert all(a["role"] == "manager" for a in body)


@pytest.mark.asyncio
async def test_manager_stats(client, db_session, admin_headers):
    manager = await _make_manager(db_session)
    user = await _make_user(db_session)
    await _make_deal(db_session, user=user, manager=manager)
    app_row = Application(
        user_id=user.id,
        product="osago",
        status="new",
        created_by="manager",
        assigned_manager_id=manager.id,
    )
    db_session.add(app_row)
    await db_session.commit()

    r = await client.get(
        f"/api/v1/admin/managers/{manager.id}/stats/", headers=admin_headers
    )
    assert r.status_code == 200, r.text
    stats = r.json()
    assert stats["applications_count"] == 1
    assert stats["deals_count"] == 1
    assert stats["certificates_count"] == 0

    r404 = await client.get(
        "/api/v1/admin/managers/999999/stats/", headers=admin_headers
    )
    assert r404.status_code == 404


@pytest.mark.asyncio
async def test_manager_permissions_update_with_audit(client, db_session, admin_headers):
    manager = await _make_manager(db_session, permissions=["chats"])

    r = await client.patch(
        f"/api/v1/admin/managers/{manager.id}/permissions/",
        json={"permissions": ["chats", "deals", "reports"]},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["permissions"] == ["chats", "deals", "reports"]

    rows = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == AuditLog.ACTION_PERMISSION_CHANGE,
            AuditLog.target_id == str(manager.id),
        )
    )
    audits = list(rows.scalars().all())
    assert audits and audits[-1].old_value == {"permissions": ["chats"]}

    # Неизвестное право → валидация
    r2 = await client.patch(
        f"/api/v1/admin/managers/{manager.id}/permissions/",
        json={"permissions": ["superpower"]},
        headers=admin_headers,
    )
    assert r2.status_code in (400, 422)


@pytest.mark.asyncio
async def test_manager_block_and_unblock(client, db_session, admin_headers):
    manager = await _make_manager(db_session)

    r = await client.patch(
        f"/api/v1/admin/managers/{manager.id}/block/",
        json={"reason": "нарушение регламента"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False

    # Повторная блокировка → 409
    r2 = await client.patch(
        f"/api/v1/admin/managers/{manager.id}/block/", json={}, headers=admin_headers
    )
    assert r2.status_code == 409

    r3 = await client.patch(
        f"/api/v1/admin/managers/{manager.id}/unblock/", headers=admin_headers
    )
    assert r3.status_code == 200
    assert r3.json()["is_active"] is True

    rows = await db_session.execute(
        select(AuditLog).where(AuditLog.target_id == str(manager.id))
    )
    actions = {e.action for e in rows.scalars().all()}
    assert {"manager_block", "manager_unblock"} <= actions


# ---------------------------------------------------------------------------
# 10.3 Admins (owner-only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admins_list_requires_owner(client, db_session, admin_headers, owner_headers):
    r = await client.get("/api/v1/admin/admins/", headers=admin_headers)
    assert r.status_code == 403

    r2 = await client.get("/api/v1/admin/admins/", headers=owner_headers)
    assert r2.status_code == 200, r2.text
    assert all(a["role"] == "admin" for a in r2.json())


@pytest.mark.asyncio
async def test_admin_permissions_update_owner_protected(
    client, db_session, admin_agent, owner_agent, admin_headers, owner_headers
):
    # Обычный админ не может менять права админов
    r = await client.patch(
        f"/api/v1/admin/admins/{admin_agent.id}/permissions/",
        json={"permissions": ["reports"]},
        headers=admin_headers,
    )
    assert r.status_code == 403

    # Владелец может
    r2 = await client.patch(
        f"/api/v1/admin/admins/{admin_agent.id}/permissions/",
        json={"permissions": ["reports"]},
        headers=owner_headers,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["permissions"] == ["reports"]

    # Владельца редактировать нельзя
    r3 = await client.patch(
        f"/api/v1/admin/admins/{owner_agent.id}/permissions/",
        json={"permissions": []},
        headers=owner_headers,
    )
    assert r3.status_code == 422


# ---------------------------------------------------------------------------
# 10.4 Reports
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deals_report(client, db_session, admin_headers):
    m1 = await _make_manager(db_session)
    m2 = await _make_manager(db_session)
    u = await _make_user(db_session)
    await _make_deal(db_session, user=u, manager=m1, amount="1000.00",
                     product="osago", policy_date=date(2026, 7, 1))
    await _make_deal(db_session, user=u, manager=m2, amount="3000.00",
                     product="kasko", policy_date=date(2026, 7, 2))
    # Вне периода — не учитывается
    await _make_deal(db_session, user=u, manager=m1, amount="9999.00",
                     product="osago", policy_date=date(2026, 6, 1))

    r = await client.get(
        "/api/v1/admin/reports/deals/",
        params={"start_date": "2026-07-01", "end_date": "2026-07-31"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_count"] == 2
    assert Decimal(str(body["total_amount"])) == Decimal("4000.00")
    assert Decimal(str(body["average_amount"])) == Decimal("2000.00")
    assert body["by_product"]["osago"]["count"] == 1
    assert Decimal(str(body["by_product"]["kasko"]["amount"])) == Decimal("3000.00")
    assert body["by_manager"][str(m1.id)]["count"] == 1
    assert body["by_manager"][str(m2.id)]["count"] == 1

    # start > end → 400
    r2 = await client.get(
        "/api/v1/admin/reports/deals/",
        params={"start_date": "2026-08-01", "end_date": "2026-07-01"},
        headers=admin_headers,
    )
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_bonuses_report(client, db_session, admin_headers):
    u1 = await _make_user(db_session)
    u2 = await _make_user(db_session)
    common = dict(
        source_user_id=u2.id,
        level=1,
        percent=Decimal("0.03"),
        base_amount=Decimal("1000.00"),
        available_at=datetime.utcnow(),
    )
    db_session.add_all(
        [
            ReferralAccrual(user_id=u1.id, amount=Decimal("30.00"),
                            status=ReferralAccrual.STATUS_CREDITED, **common),
            ReferralAccrual(user_id=u1.id, amount=Decimal("20.00"),
                            status=ReferralAccrual.STATUS_PENDING, **common),
            ReferralAccrual(user_id=u1.id, amount=Decimal("10.00"),
                            status=ReferralAccrual.STATUS_CANCELLED, **common),
        ]
    )
    await db_session.commit()

    today = date.today().isoformat()
    r = await client.get(
        "/api/v1/admin/reports/bonuses/",
        params={"start_date": today, "end_date": today},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accruals_count"] == 3
    assert Decimal(str(body["total_credited"])) == Decimal("30.00")
    assert Decimal(str(body["total_pending"])) == Decimal("20.00")
    assert Decimal(str(body["total_cancelled"])) == Decimal("10.00")


@pytest.mark.asyncio
async def test_certificates_report(client, db_session, admin_headers):
    user = await _make_user(db_session)
    partner = Partner(
        name=f"Партнёр {uuid.uuid4().hex[:6]}",
        min_exchange=Decimal("100.00"),
        max_exchange=Decimal("5000.00"),
        exchange_step=Decimal("100.00"),
        status=Partner.STATUS_ACTIVE,
    )
    chat = Chat(owner_user_id=user.id, type=Chat.TYPE_BONUS)
    db_session.add_all([partner, chat])
    await db_session.commit()
    await db_session.refresh(partner)
    await db_session.refresh(chat)

    db_session.add_all(
        [
            CertificateRequest(
                user_id=user.id, partner_id=partner.id, bonus_chat_id=chat.id,
                amount=Decimal("500.00"), status=CertificateRequest.STATUS_COMPLETED,
            ),
            CertificateRequest(
                user_id=user.id, partner_id=partner.id, bonus_chat_id=chat.id,
                amount=Decimal("300.00"), status=CertificateRequest.STATUS_COMPLETED,
            ),
            # Не completed — не попадает в отчёт
            CertificateRequest(
                user_id=user.id, partner_id=partner.id, bonus_chat_id=chat.id,
                amount=Decimal("900.00"), status=CertificateRequest.STATUS_NEW,
            ),
        ]
    )
    await db_session.commit()

    today = date.today().isoformat()
    r = await client.get(
        "/api/v1/admin/reports/certificates/",
        params={"start_date": today, "end_date": today},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_count"] == 2
    assert Decimal(str(body["total_amount"])) == Decimal("800.00")
    assert body["by_partner"][partner.name]["count"] == 2


@pytest.mark.asyncio
async def test_users_report(client, db_session, admin_headers):
    manager = await _make_manager(db_session)
    fresh = await _make_user(db_session)
    stale = await _make_user(
        db_session, updated_at=datetime.utcnow() - timedelta(days=60)
    )
    await _make_deal(db_session, user=fresh, manager=manager, policy_date=date.today())

    today = date.today().isoformat()
    r = await client.get(
        "/api/v1/admin/reports/users/",
        params={"start_date": today, "end_date": today},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["new_users"] >= 2
    assert body["active_users"] >= 1
    assert body["inactive_users"] >= 1


@pytest.mark.asyncio
async def test_referrals_report_top_referrers(client, db_session, admin_headers):
    root = await _make_user(db_session, first_name="Топ", last_name="Реферер")
    await _make_user(db_session, referrer_id=root.id)
    await _make_user(db_session, referrer_id=root.id, status=User.STATUS_BLOCKED)

    r = await client.get("/api/v1/admin/reports/referrals/", headers=admin_headers)
    assert r.status_code == 200, r.text
    top = r.json()["top_referrers"]
    entry = next(e for e in top if e["user_id"] == root.id)
    assert entry["name"] == "Топ Реферер"
    assert entry["total_referrals"] == 2
    assert entry["active_referrals"] == 1
    assert entry["active_percent"] == 50.0
    # Отсортировано по убыванию количества рефералов
    totals = [e["total_referrals"] for e in top]
    assert totals == sorted(totals, reverse=True)


# ---------------------------------------------------------------------------
# 10.5 Audit Log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_log_filters_and_export(client, db_session, admin_agent, admin_headers):
    user = await _make_user(db_session)
    rb = await client.post(
        f"/api/v1/admin/users/{user.id}/block/",
        json={"reason": "spam"},
        headers=admin_headers,
    )
    assert rb.status_code == 200, rb.text

    # Без фильтров — запись видна
    r = await client.get("/api/v1/admin/audit-log/", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert any(
        e["action"] == "user_block" and e["target_id"] == str(user.id)
        for e in r.json()
    )

    # Фильтр по действию + исполнителю
    r2 = await client.get(
        "/api/v1/admin/audit-log/",
        params={"action": "user_block", "performed_by": admin_agent.id},
        headers=admin_headers,
    )
    assert r2.status_code == 200
    assert all(e["action"] == "user_block" for e in r2.json())
    assert any(e["target_id"] == str(user.id) for e in r2.json())

    # Фильтр по несуществующему действию → 400
    r3 = await client.get(
        "/api/v1/admin/audit-log/", params={"action": "bogus"}, headers=admin_headers
    )
    assert r3.status_code == 400

    # Фильтр по дате: завтрашний день — пусто
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    r4 = await client.get(
        "/api/v1/admin/audit-log/",
        params={"start_date": tomorrow, "action": "user_block"},
        headers=admin_headers,
    )
    assert r4.json() == []

    # CSV-экспорт
    r5 = await client.get(
        "/api/v1/admin/audit-log/export/",
        params={"action": "user_block"},
        headers=admin_headers,
    )
    assert r5.status_code == 200
    assert r5.headers["content-type"].startswith("text/csv")
    lines = r5.text.strip().splitlines()
    assert lines[0].startswith("id,performed_by_type,performed_by_id,action")
    assert any("user_block" in line for line in lines[1:])


@pytest.mark.asyncio
async def test_admin_endpoints_require_admin_role(client, db_session):
    from tests.conftest import make_support_jwt

    manager = await _make_manager(db_session)
    headers = {"Authorization": f"Bearer {make_support_jwt(manager.id)}"}

    for path in (
        "/api/v1/admin/users/",
        "/api/v1/admin/managers/",
        "/api/v1/admin/reports/referrals/",
        "/api/v1/admin/audit-log/",
    ):
        r = await client.get(path, headers=headers)
        assert r.status_code == 403, f"{path}: {r.status_code}"
