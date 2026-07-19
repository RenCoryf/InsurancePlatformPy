"""Менеджерские эндпоинты заявок (право ``applications``)."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.manager_auth import get_current_manager
from app.api.deps.subject_auth import SubjectRow
from app.core.database import get_async_session
from app.models.dto.application import (
    ApplicationDetailResponse,
    ApplicationResponse,
    ApplicationStatusChangeRequest,
    ApplicationStatusEventResponse,
    ManagerApplicationCreateRequest,
)
from app.models.tables.support_agent import SupportAgent
from app.services.application_service import ApplicationService

router = APIRouter(prefix="/support/applications", tags=["support"])

_manager = get_current_manager([SupportAgent.PERMISSION_APPLICATIONS])


@router.get("/", response_model=list[ApplicationResponse])
async def list_applications(
    status_filter: str | None = Query(default=None, alias="status"),
    product: str | None = Query(default=None),
    user_id: int | None = Query(default=None),
    manager_id: int | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_async_session),
    _support: SubjectRow = Depends(_manager),
) -> list[ApplicationResponse]:
    """Все заявки с фильтрами."""
    service = ApplicationService(session)
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
    return [ApplicationResponse.model_validate(a) for a in items]


@router.post("/", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED)
async def create_application(
    payload: ManagerApplicationCreateRequest,
    session: AsyncSession = Depends(get_async_session),
    support: SubjectRow = Depends(_manager),
) -> ApplicationResponse:
    """Создать заявку от имени пользователя."""
    service = ApplicationService(session)
    try:
        app = await service.create_from_manager(
            support.support.id, payload.user_id, payload.product, payload.comment
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return ApplicationResponse.model_validate(app)


@router.get("/{application_id}/", response_model=ApplicationDetailResponse)
async def get_application(
    application_id: UUID,
    session: AsyncSession = Depends(get_async_session),
    _support: SubjectRow = Depends(_manager),
) -> ApplicationDetailResponse:
    """Детали заявки + история статусов."""
    service = ApplicationService(session)
    app = await service.get(application_id)
    if app is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="application not found")
    events = await service.get_status_events(application_id)
    return ApplicationDetailResponse(
        **ApplicationResponse.model_validate(app).model_dump(),
        status_events=[ApplicationStatusEventResponse.model_validate(e) for e in events],
    )


@router.patch("/{application_id}/status/", response_model=ApplicationResponse)
async def change_status(
    application_id: UUID,
    payload: ApplicationStatusChangeRequest,
    session: AsyncSession = Depends(get_async_session),
    support: SubjectRow = Depends(_manager),
) -> ApplicationResponse:
    """Сменить статус заявки (event + системное сообщение + SMS)."""
    service = ApplicationService(session)
    try:
        app = await service.change_status(
            application_id, payload.new_status, support.support.id, payload.comment
        )
    except ValueError as exc:
        detail = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in detail
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=detail)
    return ApplicationResponse.model_validate(app)
