from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.database import get_async_session
from app.models.users.dto import (
    BonusWithdrawalCreateRequest,
    BonusWithdrawalResponse,
)
from app.models.users.entities import User
from app.services.bonus_service import BonusService


router = APIRouter(prefix="/bonuses", tags=["bonuses"])


@router.post(
    "/withdrawals/",
    response_model=BonusWithdrawalResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_withdrawal(
    payload: BonusWithdrawalCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> BonusWithdrawalResponse:
    service = BonusService(session)
    try:
        request = await service.create_withdrawal(
            current_user, payload.amount, payload.comment
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return BonusWithdrawalResponse.model_validate(request)


@router.get("/me/withdrawals/", response_model=list[BonusWithdrawalResponse])
async def my_withdrawals(
    status_filter: str | None = Query(
        None,
        alias="status",
        pattern="^(pending|approved|rejected)$",
        description="Фильтр по статусу заявки",
    ),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[BonusWithdrawalResponse]:
    service = BonusService(session)
    items = await service.list_user_history(current_user.id, status=status_filter)
    return [BonusWithdrawalResponse.model_validate(i) for i in items]


@router.post(
    "/withdrawals/{request_id}/approve/",
    response_model=BonusWithdrawalResponse,
)
async def approve_withdrawal(
    request_id: int,
    session: AsyncSession = Depends(get_async_session),
) -> BonusWithdrawalResponse:
    """Одобрение заявки. Авторизация менеджера будет добавлена позже."""
    service = BonusService(session)
    try:
        request = await service.approve(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return BonusWithdrawalResponse.model_validate(request)


@router.post(
    "/withdrawals/{request_id}/reject/",
    response_model=BonusWithdrawalResponse,
)
async def reject_withdrawal(
    request_id: int,
    session: AsyncSession = Depends(get_async_session),
) -> BonusWithdrawalResponse:
    """Отклонение заявки: возвращает сумму обратно на баланс пользователя."""
    service = BonusService(session)
    try:
        request = await service.reject(request_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return BonusWithdrawalResponse.model_validate(request)
