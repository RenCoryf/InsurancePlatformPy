"""Пользовательские эндпоинты сделок (менеджерские — в support_deals)."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.database import get_async_session
from app.models.dto.deal import (
    DealDetailResponse,
    DealResponse,
    DealStatusEventResponse,
)
from app.models.users.entities import User
from app.services.deal_service import DealService

router = APIRouter(prefix="/deals", tags=["deals"])


@router.get("/", response_model=list[DealResponse])
async def list_deals(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[DealResponse]:
    """Список своих сделок."""
    service = DealService(session)
    items = await service.get_list({"user_id": current_user.id}, skip=skip, limit=limit)
    return [DealResponse.model_validate(d) for d in items]


@router.get("/{deal_id}/", response_model=DealDetailResponse)
async def get_deal(
    deal_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> DealDetailResponse:
    """Детали своей сделки + история статусов."""
    service = DealService(session)
    deal = await service.get(deal_id)
    if deal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="deal not found")
    if deal.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not your deal")

    events = await service.get_status_events(deal_id)
    return DealDetailResponse(
        **DealResponse.model_validate(deal).model_dump(),
        status_events=[DealStatusEventResponse.model_validate(e) for e in events],
    )
