from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.database import get_async_session
from app.models.users.dto import (
    AccrueRequest,
    BalanceResponse,
    ReferralAccrualResponse,
    StructureLevelInfo,
    StructureListResponse,
    StructureMemberInfo,
    StructureSummaryResponse,
)
from app.models.users.entities import User
from app.services.referral_service import ReferralService


router = APIRouter(prefix="/referrals", tags=["referrals"])


def _full_name(user: User) -> str:
    parts = [user.last_name, user.first_name, user.patronymic]
    name = " ".join(p for p in parts if p)
    return name or user.phone or f"Пользователь #{user.id}"


@router.get("/me/balance/", response_model=BalanceResponse)
async def my_balance(current_user: User = Depends(get_current_user)) -> BalanceResponse:
    return BalanceResponse(
        balance=current_user.balance,
        pending_balance=current_user.pending_balance,
    )


@router.get("/me/structure/", response_model=StructureSummaryResponse)
async def structure_summary(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> StructureSummaryResponse:
    service = ReferralService(session)
    data = await service.get_structure_summary(current_user)
    return StructureSummaryResponse(
        referral_code=data["referral_code"],
        referral_link=data["referral_link"],
        total=data["total"],
        levels=[StructureLevelInfo(**lvl) for lvl in data["levels"]],
    )


@router.get("/me/structure/list/", response_model=StructureListResponse)
async def structure_list(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> StructureListResponse:
    service = ReferralService(session)
    raw = await service.get_structure_list(current_user)
    levels: dict[int, list[StructureMemberInfo]] = {}
    for lvl, members in raw.items():
        levels[lvl] = [
            StructureMemberInfo(
                id=m.id,
                full_name=_full_name(m),
                phone=m.phone,
                joined_at=m.created_at,
            )
            for m in members
        ]
    return StructureListResponse(levels=levels)


@router.get("/me/accruals/", response_model=list[ReferralAccrualResponse])
async def my_accruals(
    status_filter: str | None = Query(
        None,
        alias="status",
        pattern="^(pending|credited)$",
        description="Фильтр по статусу начисления",
    ),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[ReferralAccrualResponse]:
    service = ReferralService(session)
    accruals = await service.list_accruals(current_user.id, status=status_filter)
    return [ReferralAccrualResponse.model_validate(a) for a in accruals]


@router.post("/accrue/", status_code=status.HTTP_201_CREATED)
async def accrue(
    payload: AccrueRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[ReferralAccrualResponse]:
    service = ReferralService(session)
    try:
        accruals = await service.accrue_for_source(current_user, payload.base_amount)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return [ReferralAccrualResponse.model_validate(a) for a in accruals]


@router.post("/process-pending/", response_model=BalanceResponse)
async def process_pending(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> BalanceResponse:
    service = ReferralService(session)
    await service.process_matured_accruals(user_id=current_user.id)
    await session.refresh(current_user)
    return BalanceResponse(
        balance=current_user.balance,
        pending_balance=current_user.pending_balance,
    )
