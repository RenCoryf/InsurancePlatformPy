"""Менеджерские эндпоинты сделок (право ``deals``; смена суммы — только admin)."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.manager_auth import get_current_admin, get_current_manager
from app.api.deps.redis_dep import get_redis
from app.api.deps.subject_auth import SubjectRow
from app.core.database import get_async_session
from app.models.dto.deal import (
    DealAmountUpdateRequest,
    DealCreateRequest,
    DealDetailResponse,
    DealResponse,
    DealStatusChangeRequest,
    DealStatusEventResponse,
)
from app.models.tables.support_agent import SupportAgent
from app.services.deal_service import DealService

router = APIRouter(prefix="/support/deals", tags=["support"])

_manager = get_current_manager([SupportAgent.PERMISSION_DEALS])


def _error_code(detail: str) -> int:
    return (
        status.HTTP_404_NOT_FOUND
        if "not found" in detail
        else status.HTTP_400_BAD_REQUEST
    )


@router.get("/", response_model=list[DealResponse])
async def list_deals(
    status_filter: str | None = Query(default=None, alias="status"),
    product: str | None = Query(default=None),
    user_id: int | None = Query(default=None),
    manager_id: int | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_async_session),
    _support: SubjectRow = Depends(_manager),
) -> list[DealResponse]:
    """Все сделки с фильтрами."""
    service = DealService(session)
    items = await service.get_list(
        {
            "status": status_filter,
            "product": product,
            "user_id": user_id,
            "manager_id": manager_id,
        },
        skip=skip,
        limit=limit,
    )
    return [DealResponse.model_validate(d) for d in items]


@router.post("/", response_model=DealResponse, status_code=status.HTTP_201_CREATED)
async def create_deal(
    payload: DealCreateRequest,
    session: AsyncSession = Depends(get_async_session),
    redis=Depends(get_redis),
    support: SubjectRow = Depends(_manager),
) -> DealResponse:
    """Создать сделку."""
    service = DealService(session, redis)
    try:
        deal = await service.create(
            user_id=payload.user_id,
            product=payload.product,
            policy_amount=payload.policy_amount,
            policy_date=payload.policy_date,
            manager_id=support.support.id,
            application_id=payload.application_id,
            comment=payload.comment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=_error_code(str(exc)), detail=str(exc))
    return DealResponse.model_validate(deal)


@router.get("/{deal_id}/", response_model=DealDetailResponse)
async def get_deal(
    deal_id: UUID,
    session: AsyncSession = Depends(get_async_session),
    _support: SubjectRow = Depends(_manager),
) -> DealDetailResponse:
    """Детали сделки + история статусов."""
    service = DealService(session)
    deal = await service.get(deal_id)
    if deal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="deal not found")
    events = await service.get_status_events(deal_id)
    return DealDetailResponse(
        **DealResponse.model_validate(deal).model_dump(),
        status_events=[DealStatusEventResponse.model_validate(e) for e in events],
    )


@router.patch("/{deal_id}/status/", response_model=DealResponse)
async def change_deal_status(
    deal_id: UUID,
    payload: DealStatusChangeRequest,
    session: AsyncSession = Depends(get_async_session),
    redis=Depends(get_redis),
    support: SubjectRow = Depends(_manager),
) -> DealResponse:
    """Сменить статус сделки (policy_issued начисляет бонусы, отмена — снимает)."""
    service = DealService(session, redis)
    try:
        deal = await service.change_status(
            deal_id, payload.new_status, support.support.id, payload.comment
        )
    except ValueError as exc:
        raise HTTPException(status_code=_error_code(str(exc)), detail=str(exc))
    return DealResponse.model_validate(deal)


@router.patch("/{deal_id}/amount/", response_model=DealResponse)
async def update_deal_amount(
    deal_id: UUID,
    payload: DealAmountUpdateRequest,
    session: AsyncSession = Depends(get_async_session),
    admin: SubjectRow = Depends(get_current_admin),
) -> DealResponse:
    """Изменить сумму сделки (только admin, с указанием причины)."""
    service = DealService(session)
    try:
        deal = await service.update_amount(
            deal_id, payload.new_amount, admin.support.id, payload.reason
        )
    except ValueError as exc:
        raise HTTPException(status_code=_error_code(str(exc)), detail=str(exc))
    return DealResponse.model_validate(deal)
