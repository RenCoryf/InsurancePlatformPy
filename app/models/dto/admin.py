from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.models.settings import PlatformSettings
from app.models.users.entities import User


class BlockUserRequest(BaseModel):
    reason: str = Field(..., description="Причина блокировки")
    comment: str | None = Field(None, max_length=2000, description="Комментарий администратора")

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        if v not in User.BLOCKED_REASONS:
            raise ValueError(f"reason must be one of {User.BLOCKED_REASONS}")
        return v


class UserStatusResponse(BaseModel):
    id: int
    status: str
    blocked_reason: str | None = None
    blocked_comment: str | None = None
    blocked_at: datetime | None = None
    blocked_by_admin_id: int | None = None

    class Config:
        from_attributes = True


class UserDeleteConfirmationResponse(BaseModel):
    """Первый шаг удаления: сервер выдаёт токен подтверждения."""

    confirm_required: bool = True
    confirm_token: str
    expires_in: int
    message: str = "Повторите запрос с confirm_token для окончательного удаления"


class SettingsResponse(BaseModel):
    bonus_level_1_percent: Decimal
    bonus_level_2_percent: Decimal
    bonus_level_3_percent: Decimal
    bonus_level_4_percent: Decimal
    bonus_accrual_delay_days: int
    bonus_min_exchange: Decimal
    blocked_user_level_rule: str
    sms_provider: str
    sms_sender_id: str
    sms_daily_limit_per_user: int
    root_referral_code: str | None
    root_referral_active: bool
    updated_at: datetime

    class Config:
        from_attributes = True


class SettingsUpdateRequest(BaseModel):
    bonus_level_1_percent: Decimal | None = Field(None, ge=0, le=100)
    bonus_level_2_percent: Decimal | None = Field(None, ge=0, le=100)
    bonus_level_3_percent: Decimal | None = Field(None, ge=0, le=100)
    bonus_level_4_percent: Decimal | None = Field(None, ge=0, le=100)
    bonus_accrual_delay_days: int | None = Field(None, ge=0)
    bonus_min_exchange: Decimal | None = Field(None, ge=0)
    blocked_user_level_rule: str | None = None
    sms_provider: str | None = Field(None, max_length=32)
    sms_sender_id: str | None = Field(None, max_length=32)
    sms_daily_limit_per_user: int | None = Field(None, ge=0)

    @field_validator("blocked_user_level_rule")
    @classmethod
    def validate_rule(cls, v: str | None) -> str | None:
        if v is not None and v not in PlatformSettings.BLOCKED_RULES:
            raise ValueError(
                f"blocked_user_level_rule must be one of {PlatformSettings.BLOCKED_RULES}"
            )
        return v


class RootReferralResponse(BaseModel):
    root_referral_code: str | None
    root_referral_active: bool
    root_referral_link: str | None = None
