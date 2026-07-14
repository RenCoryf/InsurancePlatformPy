"""Пользовательские эндпоинты сертификатов (менеджерские — в support_certificates)."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.database import get_async_session
from app.models.dto.certificate import (
    CertificateCreateRequest,
    CertificateDetailResponse,
    CertificateResponse,
    CertificateStatusEventResponse,
)
from app.models.users.entities import User
from app.services.certificate_service import CertificateService

router = APIRouter(prefix="/certificates", tags=["certificates"])


def _error_code(detail: str) -> int:
    return (
        status.HTTP_404_NOT_FOUND
        if "not found" in detail
        else status.HTTP_400_BAD_REQUEST
    )


@router.get("/", response_model=list[CertificateResponse])
async def list_certificates(
    status_filter: str | None = Query(default=None, alias="status"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> list[CertificateResponse]:
    """Список своих заявок на сертификаты."""
    service = CertificateService(session)
    items = await service.get_list(
        {"user_id": current_user.id, "status": status_filter}, skip=skip, limit=limit
    )
    return [CertificateResponse.model_validate(c) for c in items]


@router.post("/", response_model=CertificateResponse, status_code=status.HTTP_201_CREATED)
async def create_certificate(
    payload: CertificateCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> CertificateResponse:
    """Подать заявку на сертификат (бонусы спишутся при завершении)."""
    service = CertificateService(session)
    try:
        cert = await service.create(current_user.id, payload.partner_id, payload.amount)
    except ValueError as exc:
        raise HTTPException(status_code=_error_code(str(exc)), detail=str(exc))
    return CertificateResponse.model_validate(cert)


@router.get("/{certificate_id}/", response_model=CertificateDetailResponse)
async def get_certificate(
    certificate_id: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> CertificateDetailResponse:
    """Детали своей заявки + история статусов."""
    service = CertificateService(session)
    cert = await service.get(certificate_id)
    if cert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="certificate not found"
        )
    if cert.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="not your certificate"
        )
    events = await service.get_status_events(certificate_id)
    return CertificateDetailResponse(
        **CertificateResponse.model_validate(cert).model_dump(),
        status_events=[CertificateStatusEventResponse.model_validate(e) for e in events],
    )
