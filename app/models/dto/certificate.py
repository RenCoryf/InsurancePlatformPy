from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.certificates import CERTIFICATE_STATUSES


class CertificateCreateRequest(BaseModel):
    partner_id: int
    amount: Decimal = Field(..., gt=0)


class CertificateStatusChangeRequest(BaseModel):
    new_status: str
    comment: str | None = Field(None, max_length=2000)

    @field_validator("new_status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in CERTIFICATE_STATUSES:
            raise ValueError(f"new_status must be one of {CERTIFICATE_STATUSES}")
        return v


class CertificateCancelRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)


class CertificateResponse(BaseModel):
    id: UUID
    user_id: int
    partner_id: int
    bonus_chat_id: UUID
    amount: Decimal
    status: str
    cancel_reason: str | None
    assigned_manager_id: int | None
    certificate_file_key: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CertificateStatusEventResponse(BaseModel):
    id: int
    old_status: str | None
    new_status: str
    changed_by_type: str
    changed_by_id: int | None
    comment: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class CertificateDetailResponse(CertificateResponse):
    status_events: list[CertificateStatusEventResponse] = []


class CertificateDownloadResponse(BaseModel):
    url: str
