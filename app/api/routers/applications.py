"""Пользовательские эндпоинты заявок (менеджерские — в support_applications)."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.database import get_async_session
from app.models.dto.application import (
    ApplicationCreateRequest,
    ApplicationDetailResponse,
    ApplicationResponse,
    ApplicationStatusEventResponse,
)
from app.models.users.entities import User
from app.services.application_service import ApplicationService

router = APIRouter(prefix="/applications", tags=["applications"])


@router.get("/", response_model=list[ApplicationResponse])
async def list_applications(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[ApplicationResponse]:
    """Список своих заявок."""
    service = ApplicationService(session)
    items = await service.get_list({"user_id": current_user.id}, skip=skip, limit=limit)
    return [ApplicationResponse.model_validate(a) for a in items]


@router.post("/", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED)
async def create_application(
    payload: ApplicationCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> ApplicationResponse:
    """Создать заявку (кнопка продукта): открывается insurance-чат."""
    service = ApplicationService(session)
    try:
        app = await service.create_from_user(current_user.id, payload.product)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return ApplicationResponse.model_validate(app)


@router.get("/{application_id}/", response_model=ApplicationDetailResponse)
async def get_application(
    application_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> ApplicationDetailResponse:
    """Детали своей заявки + история статусов."""
    service = ApplicationService(session)
    app = await service.get(application_id)
    if app is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="application not found")
    if app.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not your application")

    events = await service.get_status_events(application_id)
    return ApplicationDetailResponse(
        **ApplicationResponse.model_validate(app).model_dump(),
        status_events=[ApplicationStatusEventResponse.model_validate(e) for e in events],
    )
