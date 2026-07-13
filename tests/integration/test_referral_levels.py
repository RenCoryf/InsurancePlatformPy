"""Спринт 2, БЛОК 4: 4 уровня рефералки, проценты из Settings,
правило blocked_user_level_rule, Redis-кеш аплайна, выдача структуры."""

import json
import uuid
from decimal import Decimal

import pytest
from passlib.context import CryptContext
from sqlalchemy import select

from app.models.settings import PlatformSettings
from app.models.users.entities import User
from app.models.users.referral import ReferralAccrual
from app.services.referral_service import ReferralService
from app.services.settings_service import SettingsService
from tests.conftest import make_user_jwt

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
PASSWORD_HASH = pwd.hash("Password1")

_phone_seq = {"n": 0}


def _phone() -> str:
    _phone_seq["n"] += 1
    return f"7999{uuid.uuid4().int % 10**7:07d}"


def _code() -> str:
    return uuid.uuid4().hex[:12].upper()


async def _make_user(db_session, *, referrer_id=None, status="active",
                     first_name=None, last_name=None) -> User:
    user = User(
        email=None,
        phone=_phone(),
        password_hash=PASSWORD_HASH,
        referral_code=_code(),
        referrer_id=referrer_id,
        status=status,
        first_name=first_name,
        last_name=last_name,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _make_chain(db_session, depth: int = 6) -> list[User]:
    """owner → l5 → l4 → l3 → l2 → l1 → source; возвращает [owner, l5, ..., source]."""
    chain = [await _make_user(db_session)]  # owner, referrer_id=None
    for _ in range(depth):
        chain.append(await _make_user(db_session, referrer_id=chain[-1].id))
    return chain


async def _accruals_of(db_session, source_id: int) -> list[ReferralAccrual]:
    result = await db_session.execute(
        select(ReferralAccrual).where(ReferralAccrual.source_user_id == source_id)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Начисления: 4 уровня, проценты из настроек
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accrual_only_four_levels(db_session):
    owner, l5, l4, l3, l2, l1, source = await _make_chain(db_session)

    accruals = await ReferralService(db_session).accrue_for_source(
        source, Decimal("1000")
    )

    by_user = {a.user_id: a for a in accruals}
    assert set(by_user) == {l1.id, l2.id, l3.id, l4.id}
    assert by_user[l1.id].amount == Decimal("30.00") and by_user[l1.id].level == 1
    assert by_user[l2.id].amount == Decimal("30.00") and by_user[l2.id].level == 2
    assert by_user[l3.id].amount == Decimal("20.00") and by_user[l3.id].level == 3
    assert by_user[l4.id].amount == Decimal("10.00") and by_user[l4.id].level == 4

    # 5-й уровень не начисляется
    await db_session.refresh(l5)
    assert l5.pending_balance == Decimal("0")

    await db_session.refresh(l1)
    assert l1.pending_balance == Decimal("30.00")


@pytest.mark.asyncio
async def test_accrual_percents_read_from_settings(db_session):
    await SettingsService(db_session).update(
        {"bonus_level_1_percent": "5.0", "bonus_level_2_percent": "0"}
    )
    owner, l5, l4, l3, l2, l1, source = await _make_chain(db_session)

    accruals = await ReferralService(db_session).accrue_for_source(
        source, Decimal("1000")
    )

    by_user = {a.user_id: a for a in accruals}
    assert by_user[l1.id].amount == Decimal("50.00")
    # 0% → начисление не создаётся вовсе
    assert l2.id not in by_user
    assert by_user[l3.id].amount == Decimal("20.00")


@pytest.mark.asyncio
async def test_accrual_delay_days_read_from_settings(db_session):
    await SettingsService(db_session).update({"bonus_accrual_delay_days": 1})
    owner, l5, l4, l3, l2, l1, source = await _make_chain(db_session)

    accruals = await ReferralService(db_session).accrue_for_source(
        source, Decimal("100")
    )

    delta = accruals[0].available_at - accruals[0].created_at
    assert 0 <= delta.days <= 1  # ровно сутки, а не 15 по умолчанию


# ---------------------------------------------------------------------------
# Правило для заблокированного реферера
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blocked_referrer_skip_rule_continues_upline(db_session):
    await SettingsService(db_session).update(
        {"blocked_user_level_rule": PlatformSettings.BLOCKED_RULE_SKIP}
    )
    owner, l5, l4, l3, l2, l1, source = await _make_chain(db_session)
    l2.status = User.STATUS_BLOCKED
    await db_session.commit()

    accruals = await ReferralService(db_session).accrue_for_source(
        source, Decimal("1000")
    )

    by_user = {a.user_id: a for a in accruals}
    # Уровень 2 ничего не получает, уровни 3 и 4 — получают свои проценты.
    assert set(by_user) == {l1.id, l3.id, l4.id}
    assert by_user[l3.id].amount == Decimal("20.00") and by_user[l3.id].level == 3
    assert by_user[l4.id].amount == Decimal("10.00") and by_user[l4.id].level == 4
    await db_session.refresh(l2)
    assert l2.pending_balance == Decimal("0")


@pytest.mark.asyncio
async def test_blocked_referrer_zero_rule_stops_upline(db_session):
    await SettingsService(db_session).update(
        {"blocked_user_level_rule": PlatformSettings.BLOCKED_RULE_ZERO}
    )
    owner, l5, l4, l3, l2, l1, source = await _make_chain(db_session)
    l2.status = User.STATUS_BLOCKED
    await db_session.commit()

    accruals = await ReferralService(db_session).accrue_for_source(
        source, Decimal("1000")
    )

    by_user = {a.user_id: a for a in accruals}
    # Заблокированный уровень получает 0, выше никто не получает.
    assert set(by_user) == {l1.id}


# ---------------------------------------------------------------------------
# Redis-кеш аплайна
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upline_cached_in_redis_and_invalidated(db_session, fake_redis):
    owner, l5, l4, l3, l2, l1, source = await _make_chain(db_session)
    service = ReferralService(db_session, fake_redis)

    upline = await service.get_upline_ids(source)
    assert upline == [l1.id, l2.id, l3.id, l4.id]

    key = f"referral:upline:{source.id}"
    assert json.loads(fake_redis.store[key]) == upline

    # Повторный вызов читает из кеша, а не из БД.
    fake_redis.store[key] = json.dumps([l1.id])
    assert await service.get_upline_ids(source) == [l1.id]

    await service.invalidate_upline_cache(source.id)
    assert key not in fake_redis.store
    assert await service.get_upline_ids(source) == [l1.id, l2.id, l3.id, l4.id]


# ---------------------------------------------------------------------------
# Структура: 4 уровня, приватность, число в структуре, статус
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_structure_list_four_levels_privacy_and_counts(client, db_session):
    root = await _make_user(db_session)
    a1 = await _make_user(
        db_session, referrer_id=root.id, first_name="Иван", last_name="Петров"
    )
    a2 = await _make_user(db_session, referrer_id=root.id, status=User.STATUS_BLOCKED)
    b1 = await _make_user(db_session, referrer_id=a1.id)
    c1 = await _make_user(db_session, referrer_id=b1.id)
    d1 = await _make_user(db_session, referrer_id=c1.id)
    e1 = await _make_user(db_session, referrer_id=d1.id)  # 5-й уровень от root

    headers = {"Authorization": f"Bearer {make_user_jwt(root.id)}"}
    r = await client.get("/api/v1/referrals/me/structure/list/", headers=headers)
    assert r.status_code == 200, r.text
    levels = r.json()["levels"]

    assert set(levels) == {"1", "2", "3", "4"}
    shown_ids = {m["id"] for lvl in levels.values() for m in lvl}
    assert e1.id not in shown_ids  # 5-й уровень не отображается

    level1 = {m["id"]: m for m in levels["1"]}
    assert set(level1) == {a1.id, a2.id}
    # Приватность: имя + первая буква фамилии, телефона в ответе нет.
    assert level1[a1.id]["name"] == "Иван П."
    assert "phone" not in level1[a1.id]
    assert level1[a1.id]["joined_at"]
    assert level1[a2.id]["status"] == User.STATUS_BLOCKED
    # Число в структуре: у a1 вниз — b1, c1, d1, e1 (4 уровня от a1).
    assert level1[a1.id]["structure_count"] == 4
    assert {m["id"]: m["structure_count"] for m in levels["2"]} == {b1.id: 3}


@pytest.mark.asyncio
async def test_structure_summary_counts_four_levels(db_session):
    root = await _make_user(db_session)
    a1 = await _make_user(db_session, referrer_id=root.id)
    b1 = await _make_user(db_session, referrer_id=a1.id)
    c1 = await _make_user(db_session, referrer_id=b1.id)
    d1 = await _make_user(db_session, referrer_id=c1.id)
    await _make_user(db_session, referrer_id=d1.id)  # уровень 5 — не в сводке

    summary = await ReferralService(db_session).get_structure_summary(root)
    assert summary["total"] == 4
    assert [lvl["level"] for lvl in summary["levels"]] == [1, 2, 3, 4]
