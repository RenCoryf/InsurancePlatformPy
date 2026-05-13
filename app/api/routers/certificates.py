from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.utils import not_implemented


class CertificateCreate(BaseModel):
    partner_id: str
    amount: float


class CertificateResponse(BaseModel):
    id: str
    status: str


router = APIRouter(prefix="/certificates", tags=["certificates"])


@router.post("/", response_model=CertificateResponse, status_code=status.HTTP_201_CREATED)
async def create_certificate(payload: CertificateCreate) -> CertificateResponse:
    not_implemented("Request a certificate")


@router.get("/", response_model=list[CertificateResponse])
async def list_certificates() -> list[CertificateResponse]:
    not_implemented("List user or manager certificate requests")


@router.post("/{certificate_id}/confirm/")
async def confirm_certificate(certificate_id: str) -> CertificateResponse:
    not_implemented("Manager confirms certificate")


@router.post("/{certificate_id}/start/")
async def start_certificate(certificate_id: str) -> CertificateResponse:
    not_implemented("Manager starts certificate processing")


@router.post("/{certificate_id}/complete/")
async def complete_certificate(certificate_id: str, file_id: str | None = None) -> CertificateResponse:
    not_implemented("Manager completes certificate and attaches file")


@router.post("/{certificate_id}/cancel/")
async def cancel_certificate(certificate_id: str, reason: str = "") -> CertificateResponse:
    not_implemented("Manager cancels certificate")
