"""Админ-панель, раздел Users: список с поиском, карточка пользователя,
ручные операции с бонусами и CSV-экспорт.

Блокировка/разблокировка/удаление живут в :mod:`app.api.routers.admin`
(появились в спринте с модерацией) — здесь не дублируются.
"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.manager_auth import get_current_admin
from app.api.deps.subject_auth import SubjectRow
from app.core.database import get_async_session
from app.models.applications import Application
from app.models.audit_log import AuditLog
from app.models.deals import Deal
from app.models.dto.admin import (
    AdminUserBalanceResponse,
    AdminUserDetailResponse,
    AdminUserResponse,
    AuditLogEntryResponse,
    BonusChangeRequest,
)
from app.models.dto.application import ApplicationResponse
from app.models.dto.deal import DealResponse
from app.models.users.dto import ReferralAccrualResponse, StructureMemberInfo
from app.models.users.entities import User
from app.models.users.referral import ReferralAccrual
from app.services.bonus_service import BonusService
from app.services.referral_service import ReferralService

router = APIRouter(prefix="/admin/users", tags=["admin"])


def _full_name(user: User) -> str:
    name = " ".join(p for p in (user.first_name, user.last_name) if p)
    return name or f"Пользователь #{user.id}"


@router.get("/", response_model=list[AdminUserResponse])
async def list_users(
    search: str | None = Query(default=None, max_length=100),
    status_filter: str | None = Query(default=None, alias="status"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_async_session),
    _admin: SubjectRow = Depends(get_current_admin),
) -> list[AdminUserResponse]:
    """Список пользователей с поиском по ФИО/телефону/email и фильтром по статусу."""
    stmt = select(User).order_by(User.created_at.desc(), User.id.desc())

    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(
                User.first_name.ilike(pattern),
                User.last_name.ilike(pattern),
                User.phone.ilike(pattern),
                User.email.ilike(pattern),
            )
        )

    if status_filter:
        if status_filter not in User.STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"status must be one of {User.STATUSES}",
            )
        stmt = stmt.where(User.status == status_filter)

    result = await session.execute(stmt.offset(skip).limit(limit))
    return [AdminUserResponse.model_validate(u) for u in result.scalars().all()]


@router.get("/export/", response_class=StreamingResponse)
async def export_users_csv(
    session: AsyncSession = Depends(get_async_session),
    _admin: SubjectRow = Depends(get_current_admin),
) -> StreamingResponse:
    """Экспорт всех пользователей в CSV."""
    result = await session.execute(select(User).order_by(User.id))
    users = list(result.scalars().all())

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "id", "first_name", "last_name", "phone", "email", "status",
            "balance", "pending_balance", "referral_code", "referrer_id",
            "created_at",
        ],
    )
    writer.writeheader()
    for user in users:
        writer.writerow(
            {
                "id": user.id,
                "first_name": user.first_name or "",
                "last_name": user.last_name or "",
                "phone": user.phone or "",
                "email": user.email or "",
                "status": user.status,
                "balance": str(user.balance),
                "pending_balance": str(user.pending_balance),
                "referral_code": user.referral_code,
                "referrer_id": user.referrer_id or "",
                "created_at": user.created_at.isoformat(),
            }
        )

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=users.csv"},
    )


async def _get_user_or_404(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return user


@router.get("/{user_id}/", response_model=AdminUserDetailResponse)
async def get_user_card(
    user_id: int,
    session: AsyncSession = Depends(get_async_session),
    _admin: SubjectRow = Depends(get_current_admin),
) -> AdminUserDetailResponse:
    """Карточка пользователя: структура на 4 уровня, заявки, сделки,
    начисления и записи журнала по этому пользователю."""
    user = await _get_user_or_404(session, user_id)

    raw_structure = await ReferralService(session).get_structure_list(user)
    referrals = {
        lvl: [
            StructureMemberInfo(
                id=m.user.id,
                name=_full_name(m.user),
                joined_at=m.user.created_at,
                structure_count=m.structure_count,
                status=m.user.status,
            )
            for m in members
        ]
        for lvl, members in raw_structure.items()
    }

    applications = await session.execute(
        select(Application)
        .where(Application.user_id == user_id)
        .order_by(Application.created_at.desc())
    )
    deals = await session.execute(
        select(Deal).where(Deal.user_id == user_id).order_by(Deal.created_at.desc())
    )
    accruals = await session.execute(
        select(ReferralAccrual)
        .where(ReferralAccrual.user_id == user_id)
        .order_by(ReferralAccrual.created_at.desc())
    )
    audit_logs = await session.execute(
        select(AuditLog)
        .where(
            AuditLog.target_type == AuditLog.TARGET_USER,
            AuditLog.target_id == str(user_id),
        )
        .order_by(AuditLog.created_at.desc())
    )

    return AdminUserDetailResponse(
        **AdminUserResponse.model_validate(user).model_dump(),
        referrals=referrals,
        applications=[
            ApplicationResponse.model_validate(a) for a in applications.scalars().all()
        ],
        deals=[DealResponse.model_validate(d) for d in deals.scalars().all()],
        accruals=[
            ReferralAccrualResponse.model_validate(a) for a in accruals.scalars().all()
        ],
        audit_logs=[
            AuditLogEntryResponse.model_validate(entry)
            for entry in audit_logs.scalars().all()
        ],
    )


@router.post("/{user_id}/bonus/credit/", response_model=AdminUserBalanceResponse)
async def credit_bonus(
    user_id: int,
    payload: BonusChangeRequest,
    session: AsyncSession = Depends(get_async_session),
    admin: SubjectRow = Depends(get_current_admin),
) -> AdminUserBalanceResponse:
    """Ручное начисление бонусов (с записью в audit_log и SMS)."""
    await _get_user_or_404(session, user_id)
    try:
        user = await BonusService(session).credit(
            user_id=user_id,
            amount=payload.amount,
            reason=payload.reason,
            performed_by=admin.support.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    return AdminUserBalanceResponse.model_validate(user)


@router.post("/{user_id}/bonus/debit/", response_model=AdminUserBalanceResponse)
async def debit_bonus(
    user_id: int,
    payload: BonusChangeRequest,
    session: AsyncSession = Depends(get_async_session),
    admin: SubjectRow = Depends(get_current_admin),
) -> AdminUserBalanceResponse:
    """Ручное списание бонусов (с записью в audit_log)."""
    await _get_user_or_404(session, user_id)
    try:
        user = await BonusService(session).debit(
            user_id=user_id,
            amount=payload.amount,
            reason=payload.reason,
            performed_by=admin.support.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    return AdminUserBalanceResponse.model_validate(user)
