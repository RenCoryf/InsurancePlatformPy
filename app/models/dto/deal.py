from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.applications import APPLICATION_STATUSES, PRODUCTS


class DealCreateRequest(BaseModel):
    user_id: int
    product: str
    policy_amount: Decimal = Field(..., gt=0)
    policy_date: date
    application_id: UUID | None = None
    comment: str | None = Field(None, max_length=2000)

    @field_validator("product")
    @classmethod
    def validate_product(cls, v: str) -> str:
        if v not in PRODUCTS:
            raise ValueError(f"product must be one of {PRODUCTS}")
        return v


class DealStatusChangeRequest(BaseModel):
    new_status: str
    comment: str | None = Field(None, max_length=2000)

    @field_validator("new_status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in APPLICATION_STATUSES:
            raise ValueError(f"new_status must be one of {APPLICATION_STATUSES}")
        return v


class DealAmountUpdateRequest(BaseModel):
    new_amount: Decimal = Field(..., gt=0)
    reason: str = Field(..., min_length=1, max_length=2000)


class DealResponse(BaseModel):
    id: UUID
    application_id: UUID | None
    user_id: int
    product: str
    policy_amount: Decimal
    policy_date: date
    accrual_date: date
    status: str
    assigned_manager_id: int
    comment: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DealStatusEventResponse(BaseModel):
    id: int
    old_status: str | None
    new_status: str
    changed_by_type: str
    changed_by_id: int | None
    comment: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class DealDetailResponse(DealResponse):
    status_events: list[DealStatusEventResponse] = []
