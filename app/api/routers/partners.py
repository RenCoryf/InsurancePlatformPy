"""Пользовательские эндпоинты партнёров (админские — в admin_partners)."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.database import get_async_session
from app.models.dto.partner import PartnerResponse
from app.models.partners import Partner
from app.models.users.entities import User
from app.services.partner_service import PartnerService

router = APIRouter(prefix="/partners", tags=["partners"])


@router.get("/", response_model=list[PartnerResponse])
async def list_partners(
    _current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[PartnerResponse]:
    """Активные партнёры для обмена бонусов."""
    items = await PartnerService(session).get_active_list()
    return [PartnerResponse.model_validate(p) for p in items]


@router.get("/{partner_id}/", response_model=PartnerResponse)
async def get_partner(
    partner_id: int,
    _current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> PartnerResponse:
    """Детали активного партнёра."""
    partner = await PartnerService(session).get(partner_id)
    if partner is None or partner.status != Partner.STATUS_ACTIVE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="partner not found")
    return PartnerResponse.model_validate(partner)
