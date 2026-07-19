from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.applications import APPLICATION_STATUSES, PRODUCTS


def _validate_product(v: str) -> str:
    if v not in PRODUCTS:
        raise ValueError(f"product must be one of {PRODUCTS}")
    return v


class ApplicationCreateRequest(BaseModel):
    product: str = Field(..., description="Продукт: osago/kasko/property/personal/pds/legal")

    @field_validator("product")
    @classmethod
    def validate_product(cls, v: str) -> str:
        return _validate_product(v)


class ManagerApplicationCreateRequest(ApplicationCreateRequest):
    user_id: int
    comment: str | None = Field(None, max_length=2000)


class ApplicationStatusChangeRequest(BaseModel):
    new_status: str
    comment: str | None = Field(None, max_length=2000)

    @field_validator("new_status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in APPLICATION_STATUSES:
            raise ValueError(f"new_status must be one of {APPLICATION_STATUSES}")
        return v


class ApplicationResponse(BaseModel):
    id: UUID
    user_id: int
    chat_id: UUID | None
    product: str
    status: str
    assigned_manager_id: int | None
    manager_comment: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ApplicationStatusEventResponse(BaseModel):
    id: int
    old_status: str | None
    new_status: str
    changed_by_type: str
    changed_by_id: int | None
    comment: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class ApplicationDetailResponse(ApplicationResponse):
    status_events: list[ApplicationStatusEventResponse] = []
