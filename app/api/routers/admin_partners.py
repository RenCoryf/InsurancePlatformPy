"""Админские эндпоинты партнёров (создание/обновление, логотип в MinIO).

Создание и обновление принимают multipart/form-data — вместе с полями
можно передать файл логотипа ``logo_file``.
"""
import io
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.manager_auth import get_current_admin
from app.api.deps.subject_auth import SubjectRow
from app.core.database import get_async_session
from app.models.dto.partner import PartnerResponse
from app.services.partner_service import PartnerService

router = APIRouter(prefix="/admin/partners", tags=["admin"])


def _error_code(detail: str) -> int:
    return (
        status.HTTP_404_NOT_FOUND
        if "not found" in detail
        else status.HTTP_400_BAD_REQUEST
    )


async def _logo_tuple(logo_file: UploadFile | None):
    if logo_file is None or not (logo_file.filename or logo_file.size):
        return None
    size = logo_file.size
    if size is None:
        body = await logo_file.read()
        size = len(body)
        stream = io.BytesIO(body)
    else:
        stream = logo_file.file
    return stream, size, logo_file.content_type or "application/octet-stream"


@router.get("/", response_model=list[PartnerResponse])
async def list_partners(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_async_session),
    _admin: SubjectRow = Depends(get_current_admin),
) -> list[PartnerResponse]:
    """Все партнёры, включая неактивных."""
    items = await PartnerService(session).get_all(skip=skip, limit=limit)
    return [PartnerResponse.model_validate(p) for p in items]


@router.post("/", response_model=PartnerResponse, status_code=status.HTTP_201_CREATED)
async def create_partner(
    request: Request,
    name: str = Form(..., min_length=1, max_length=255),
    min_exchange: Decimal = Form(..., gt=0),
    max_exchange: Decimal | None = Form(default=None),
    exchange_step: Decimal = Form(default=Decimal("100"), gt=0),
    logo_file: UploadFile | None = File(default=None),
    session: AsyncSession = Depends(get_async_session),
    admin: SubjectRow = Depends(get_current_admin),
) -> PartnerResponse:
    """Создать партнёра."""
    minio_client = getattr(request.app.state, "minio", None)
    service = PartnerService(session, minio_client)
    try:
        partner = await service.create(
            name=name,
            min_exchange=min_exchange,
            max_exchange=max_exchange,
            exchange_step=exchange_step,
            admin_id=admin.support.id,
            logo=await _logo_tuple(logo_file),
        )
    except ValueError as exc:
        raise HTTPException(status_code=_error_code(str(exc)), detail=str(exc))
    return PartnerResponse.model_validate(partner)


@router.patch("/{partner_id}/", response_model=PartnerResponse)
async def update_partner(
    partner_id: int,
    request: Request,
    name: str | None = Form(default=None, max_length=255),
    min_exchange: Decimal | None = Form(default=None),
    max_exchange: Decimal | None = Form(default=None),
    exchange_step: Decimal | None = Form(default=None),
    status_value: str | None = Form(default=None, alias="status"),
    logo_file: UploadFile | None = File(default=None),
    session: AsyncSession = Depends(get_async_session),
    admin: SubjectRow = Depends(get_current_admin),
) -> PartnerResponse:
    """Обновить партнёра (частично)."""
    minio_client = getattr(request.app.state, "minio", None)
    service = PartnerService(session, minio_client)
    try:
        partner = await service.update(
            partner_id,
            admin_id=admin.support.id,
            name=name,
            min_exchange=min_exchange,
            max_exchange=max_exchange,
            exchange_step=exchange_step,
            status=status_value,
            logo=await _logo_tuple(logo_file),
        )
    except ValueError as exc:
        raise HTTPException(status_code=_error_code(str(exc)), detail=str(exc))
    return PartnerResponse.model_validate(partner)
