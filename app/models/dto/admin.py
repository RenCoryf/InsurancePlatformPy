from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.models.dto.application import ApplicationResponse
from app.models.dto.deal import DealResponse
from app.models.settings import PlatformSettings
from app.models.users.dto import ReferralAccrualResponse, StructureMemberInfo
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
    sms_templates: dict[str, str] = {}
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
    sms_templates: dict[str, str] | None = None

    @field_validator("sms_templates")
    @classmethod
    def validate_sms_templates(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        if v is None:
            return None
        from app.services.notification_service import DEFAULT_SMS_TEMPLATES

        unknown = set(v) - set(DEFAULT_SMS_TEMPLATES)
        if unknown:
            raise ValueError(f"unknown SMS templates: {', '.join(sorted(unknown))}")
        return v

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


# ---------------------------------------------------------------------------
# Раздел Users
# ---------------------------------------------------------------------------


class AdminUserResponse(BaseModel):
    """Пользователь глазами администратора (полные данные, без хеша пароля)."""

    id: int
    first_name: str | None
    last_name: str | None
    patronymic: str | None
    phone: str | None
    email: str | None
    status: str
    balance: Decimal
    pending_balance: Decimal
    referral_code: str
    referrer_id: int | None
    blocked_reason: str | None = None
    blocked_at: datetime | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class AuditLogEntryResponse(BaseModel):
    id: int
    performed_by_type: str
    performed_by_id: int | None
    action: str
    target_type: str
    target_id: str
    old_value: dict | None
    new_value: dict | None
    comment: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class AdminUserDetailResponse(AdminUserResponse):
    """Карточка пользователя: реферальная структура на 4 уровня вниз,
    заявки, сделки, история начислений и связанные записи журнала."""

    referrals: dict[int, list[StructureMemberInfo]] = {}
    applications: list[ApplicationResponse] = []
    deals: list[DealResponse] = []
    accruals: list[ReferralAccrualResponse] = []
    audit_logs: list[AuditLogEntryResponse] = []


class BonusChangeRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, description="Сумма бонусов")
    reason: str = Field(..., min_length=1, max_length=2000, description="Причина")


class AdminUserBalanceResponse(BaseModel):
    id: int
    balance: Decimal
    pending_balance: Decimal

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Разделы Managers / Admins
# ---------------------------------------------------------------------------


class ManagerStatsResponse(BaseModel):
    manager_id: int
    applications_count: int
    deals_count: int
    certificates_count: int
    # Среднее время ответа в чате; заполнится при появлении логирования.
    average_response_time_seconds: float | None = None


class PermissionsUpdateRequest(BaseModel):
    permissions: list[str]

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, v: list[str]) -> list[str]:
        from app.models.dto.support_agent import _validate_permissions

        return _validate_permissions(v)


class ManagerBlockRequest(BaseModel):
    reason: str | None = Field(None, max_length=2000)


# ---------------------------------------------------------------------------
# Раздел Reports
# ---------------------------------------------------------------------------


class ProductAggregate(BaseModel):
    count: int
    amount: Decimal


class DealsReportResponse(BaseModel):
    period: list[date]
    total_count: int
    total_amount: Decimal
    average_amount: Decimal
    by_product: dict[str, ProductAggregate]
    by_manager: dict[int, ProductAggregate]


class BonusesReportResponse(BaseModel):
    period: list[date]
    total_credited: Decimal
    total_pending: Decimal
    total_cancelled: Decimal
    accruals_count: int


class CertificatesReportResponse(BaseModel):
    period: list[date]
    total_count: int
    total_amount: Decimal
    by_partner: dict[str, ProductAggregate]


class UsersReportResponse(BaseModel):
    period: list[date]
    new_users: int
    active_users: int
    inactive_users: int


class TopReferrerInfo(BaseModel):
    user_id: int
    name: str
    total_referrals: int
    active_referrals: int
    active_percent: float


class ReferralsReportResponse(BaseModel):
    top_referrers: list[TopReferrerInfo]
