"""Менеджерские эндпоинты сертификатов (право ``certificates``)."""
import io
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.manager_auth import get_current_manager
from app.api.deps.subject_auth import SubjectRow
from app.core.database import get_async_session
from app.models.dto.certificate import (
    CertificateCancelRequest,
    CertificateDownloadResponse,
    CertificateResponse,
    CertificateStatusChangeRequest,
)
from app.models.tables.support_agent import SupportAgent
from app.services.certificate_service import CertificateService

router = APIRouter(prefix="/support/certificates", tags=["support"])

_manager = get_current_manager([SupportAgent.PERMISSION_CERTIFICATES])


def _error_code(detail: str) -> int:
    return (
        status.HTTP_404_NOT_FOUND
        if "not found" in detail
        else status.HTTP_400_BAD_REQUEST
    )


@router.get("/", response_model=list[CertificateResponse])
async def list_certificates(
    status_filter: str | None = Query(default=None, alias="status"),
    partner_id: int | None = Query(default=None),
    user_id: int | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_async_session),
    _support: SubjectRow = Depends(_manager),
) -> list[CertificateResponse]:
    """Все заявки на сертификаты с фильтрами."""
    service = CertificateService(session)
    items = await service.get_list(
        {"status": status_filter, "partner_id": partner_id, "user_id": user_id},
        skip=skip,
        limit=limit,
    )
    return [CertificateResponse.model_validate(c) for c in items]


@router.patch("/{certificate_id}/status/", response_model=CertificateResponse)
async def change_certificate_status(
    certificate_id: UUID,
    payload: CertificateStatusChangeRequest,
    session: AsyncSession = Depends(get_async_session),
    support: SubjectRow = Depends(_manager),
) -> CertificateResponse:
    """Сменить статус заявки (new → confirming → in_progress)."""
    service = CertificateService(session)
    try:
        cert = await service.change_status(
            certificate_id, payload.new_status, support.support.id, payload.comment
        )
    except ValueError as exc:
        raise HTTPException(status_code=_error_code(str(exc)), detail=str(exc))
    return CertificateResponse.model_validate(cert)


@router.post("/{certificate_id}/complete/", response_model=CertificateResponse)
async def complete_certificate(
    certificate_id: UUID,
    request: Request,
    certificate_file: UploadFile = File(...),
    session: AsyncSession = Depends(get_async_session),
    support: SubjectRow = Depends(_manager),
) -> CertificateResponse:
    """Завершить заявку: прикрепить файл сертификата и списать бонусы."""
    minio_client = getattr(request.app.state, "minio", None)
    service = CertificateService(session, minio_client)

    size = certificate_file.size
    if size is None:
        body = await certificate_file.read()
        size = len(body)
        stream = io.BytesIO(body)
    else:
        stream = certificate_file.file

    try:
        cert = await service.complete(
            certificate_id,
            support.support.id,
            stream=stream,
            size_bytes=size,
            content_type=certificate_file.content_type or "application/octet-stream",
        )
    except ValueError as exc:
        raise HTTPException(status_code=_error_code(str(exc)), detail=str(exc))
    return CertificateResponse.model_validate(cert)


@router.post("/{certificate_id}/cancel/", response_model=CertificateResponse)
async def cancel_certificate(
    certificate_id: UUID,
    payload: CertificateCancelRequest,
    session: AsyncSession = Depends(get_async_session),
    support: SubjectRow = Depends(_manager),
) -> CertificateResponse:
    """Отменить заявку (списанные бонусы не возвращаются)."""
    service = CertificateService(session)
    try:
        cert = await service.cancel(certificate_id, support.support.id, payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=_error_code(str(exc)), detail=str(exc))
    return CertificateResponse.model_validate(cert)


@router.post("/{certificate_id}/download/", response_model=CertificateDownloadResponse)
async def download_certificate(
    certificate_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    _support: SubjectRow = Depends(_manager),
) -> CertificateDownloadResponse:
    """Получить ссылку на скачивание файла сертификата."""
    minio_client = getattr(request.app.state, "minio", None)
    service = CertificateService(session, minio_client)
    try:
        url = await service.get_download_url(certificate_id)
    except ValueError as exc:
        raise HTTPException(status_code=_error_code(str(exc)), detail=str(exc))
    return CertificateDownloadResponse(url=url)
