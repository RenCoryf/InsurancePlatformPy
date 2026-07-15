"""Админ-панель, раздел Reports: агрегированные отчёты за период.

Все агрегаты считаются в SQL (count/sum/group by), в Python — только сборка
ответа. Даты-границы включительны; для timestamp-полей период разворачивается
в [start 00:00; end 23:59:59.999999].
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.manager_auth import get_current_admin
from app.api.deps.subject_auth import SubjectRow
from app.core.database import get_async_session
from app.models.certificates import CertificateRequest
from app.models.deals import Deal
from app.models.dto.admin import (
    BonusesReportResponse,
    CertificatesReportResponse,
    DealsReportResponse,
    ProductAggregate,
    ReferralsReportResponse,
    TopReferrerInfo,
    UsersReportResponse,
)
from app.models.partners import Partner
from app.models.users.entities import User
from app.models.users.referral import ReferralAccrual

router = APIRouter(prefix="/admin/reports", tags=["admin"])

INACTIVITY_DAYS = 30


def _validate_period(start_date: date, end_date: date) -> None:
    if start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date must not be after end_date",
        )


def _day_bounds(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    return datetime.combine(start_date, time.min), datetime.combine(end_date, time.max)


@router.get("/deals/", response_model=DealsReportResponse)
async def deals_report(
    start_date: date = Query(...),
    end_date: date = Query(...),
    session: AsyncSession = Depends(get_async_session),
    _admin: SubjectRow = Depends(get_current_admin),
) -> DealsReportResponse:
    """Сделки за период: итоги, разрез по продуктам и менеджерам."""
    _validate_period(start_date, end_date)
    period_filter = (Deal.policy_date >= start_date, Deal.policy_date <= end_date)

    totals = (
        await session.execute(
            select(func.count(), func.coalesce(func.sum(Deal.policy_amount), 0)).where(
                *period_filter
            )
        )
    ).one()
    total_count, total_amount = int(totals[0]), Decimal(totals[1])

    by_product_rows = await session.execute(
        select(
            Deal.product,
            func.count(),
            func.coalesce(func.sum(Deal.policy_amount), 0),
        )
        .where(*period_filter)
        .group_by(Deal.product)
    )
    by_manager_rows = await session.execute(
        select(
            Deal.assigned_manager_id,
            func.count(),
            func.coalesce(func.sum(Deal.policy_amount), 0),
        )
        .where(*period_filter)
        .group_by(Deal.assigned_manager_id)
    )

    return DealsReportResponse(
        period=[start_date, end_date],
        total_count=total_count,
        total_amount=total_amount,
        average_amount=(
            (total_amount / total_count).quantize(Decimal("0.01"))
            if total_count
            else Decimal("0")
        ),
        by_product={
            product: ProductAggregate(count=int(count), amount=Decimal(amount))
            for product, count, amount in by_product_rows.all()
        },
        by_manager={
            int(manager_id): ProductAggregate(count=int(count), amount=Decimal(amount))
            for manager_id, count, amount in by_manager_rows.all()
        },
    )


@router.get("/bonuses/", response_model=BonusesReportResponse)
async def bonuses_report(
    start_date: date = Query(...),
    end_date: date = Query(...),
    session: AsyncSession = Depends(get_async_session),
    _admin: SubjectRow = Depends(get_current_admin),
) -> BonusesReportResponse:
    """Реферальные начисления за период в разрезе статусов."""
    _validate_period(start_date, end_date)
    start_dt, end_dt = _day_bounds(start_date, end_date)

    def _sum_for(status_value: str):
        return func.coalesce(
            func.sum(
                case((ReferralAccrual.status == status_value, ReferralAccrual.amount))
            ),
            0,
        )

    row = (
        await session.execute(
            select(
                func.count(),
                _sum_for(ReferralAccrual.STATUS_CREDITED),
                _sum_for(ReferralAccrual.STATUS_PENDING),
                _sum_for(ReferralAccrual.STATUS_CANCELLED),
            ).where(
                ReferralAccrual.created_at >= start_dt,
                ReferralAccrual.created_at <= end_dt,
            )
        )
    ).one()

    return BonusesReportResponse(
        period=[start_date, end_date],
        accruals_count=int(row[0]),
        total_credited=Decimal(row[1]),
        total_pending=Decimal(row[2]),
        total_cancelled=Decimal(row[3]),
    )


@router.get("/certificates/", response_model=CertificatesReportResponse)
async def certificates_report(
    start_date: date = Query(...),
    end_date: date = Query(...),
    session: AsyncSession = Depends(get_async_session),
    _admin: SubjectRow = Depends(get_current_admin),
) -> CertificatesReportResponse:
    """Завершённые сертификаты за период в разрезе партнёров."""
    _validate_period(start_date, end_date)
    start_dt, end_dt = _day_bounds(start_date, end_date)

    rows = await session.execute(
        select(
            Partner.name,
            func.count(),
            func.coalesce(func.sum(CertificateRequest.amount), 0),
        )
        .join(Partner, Partner.id == CertificateRequest.partner_id)
        .where(
            CertificateRequest.status == CertificateRequest.STATUS_COMPLETED,
            CertificateRequest.created_at >= start_dt,
            CertificateRequest.created_at <= end_dt,
        )
        .group_by(Partner.name)
    )

    by_partner: dict[str, ProductAggregate] = {}
    total_count = 0
    total_amount = Decimal("0")
    for name, count, amount in rows.all():
        by_partner[name] = ProductAggregate(count=int(count), amount=Decimal(amount))
        total_count += int(count)
        total_amount += Decimal(amount)

    return CertificatesReportResponse(
        period=[start_date, end_date],
        total_count=total_count,
        total_amount=total_amount,
        by_partner=by_partner,
    )


@router.get("/users/", response_model=UsersReportResponse)
async def users_report(
    start_date: date = Query(...),
    end_date: date = Query(...),
    session: AsyncSession = Depends(get_async_session),
    _admin: SubjectRow = Depends(get_current_admin),
) -> UsersReportResponse:
    """Пользователи: новые за период, активные (со сделкой за период),
    неактивные (> 30 дней без изменений)."""
    _validate_period(start_date, end_date)
    start_dt, end_dt = _day_bounds(start_date, end_date)

    new_users = (
        await session.execute(
            select(func.count())
            .select_from(User)
            .where(User.created_at >= start_dt, User.created_at <= end_dt)
        )
    ).scalar_one()

    active_users = (
        await session.execute(
            select(func.count(func.distinct(Deal.user_id))).where(
                Deal.policy_date >= start_date, Deal.policy_date <= end_date
            )
        )
    ).scalar_one()

    inactivity_threshold = datetime.utcnow() - timedelta(days=INACTIVITY_DAYS)
    inactive_users = (
        await session.execute(
            select(func.count())
            .select_from(User)
            .where(
                User.status == User.STATUS_ACTIVE,
                User.updated_at < inactivity_threshold,
            )
        )
    ).scalar_one()

    return UsersReportResponse(
        period=[start_date, end_date],
        new_users=int(new_users),
        active_users=int(active_users),
        inactive_users=int(inactive_users),
    )


@router.get("/referrals/", response_model=ReferralsReportResponse)
async def referrals_report(
    limit: int = Query(default=10, ge=1, le=100),
    session: AsyncSession = Depends(get_async_session),
    _admin: SubjectRow = Depends(get_current_admin),
) -> ReferralsReportResponse:
    """Топ рефереров по числу приглашённых (1-й уровень)."""
    referral = select(
        User.referrer_id.label("referrer_id"),
        func.count().label("total"),
        func.coalesce(
            func.sum(case((User.status == User.STATUS_ACTIVE, 1), else_=0)), 0
        ).label("active"),
    ).where(User.referrer_id.isnot(None)).group_by(User.referrer_id).subquery()

    rows = await session.execute(
        select(User, referral.c.total, referral.c.active)
        .join(referral, referral.c.referrer_id == User.id)
        .order_by(referral.c.total.desc(), User.id)
        .limit(limit)
    )

    top: list[TopReferrerInfo] = []
    for user, total, active in rows.all():
        name = " ".join(p for p in (user.first_name, user.last_name) if p)
        top.append(
            TopReferrerInfo(
                user_id=user.id,
                name=name or f"Пользователь #{user.id}",
                total_referrals=int(total),
                active_referrals=int(active),
                active_percent=round(int(active) / int(total) * 100, 2) if total else 0.0,
            )
        )
    return ReferralsReportResponse(top_referrers=top)
