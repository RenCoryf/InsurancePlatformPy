from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserRegisterRequest(BaseModel):
    email: EmailStr = Field(..., description="User email address")
    phone: str = Field(..., min_length=10, max_length=20, description="Phone number")
    password: str = Field(..., min_length=8, max_length=128, description="Password")
    first_name: str | None = Field(None, max_length=100, description="First name")
    last_name: str | None = Field(None, max_length=100, description="Last name")
    patronymic: str | None = Field(None, max_length=100, description="Patronymic")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        digits_only = "".join(c for c in v if c.isdigit())
        if len(digits_only) < 10:
            raise ValueError("Phone must contain at least 10 digits")
        return digits_only

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class UserResponse(BaseModel):
    id: int
    email: str | None
    phone: str | None
    first_name: str | None
    last_name: str | None
    patronymic: str | None
    balance: Decimal = Decimal("0")
    pending_balance: Decimal = Decimal("0")
    referral_code: str | None = None
    status: str = "active"

    class Config:
        from_attributes = True


class BalanceResponse(BaseModel):
    balance: Decimal
    pending_balance: Decimal


class ReferralAccrualResponse(BaseModel):
    id: int
    source_user_id: int
    level: int
    percent: Decimal
    base_amount: Decimal
    amount: Decimal
    status: str
    created_at: datetime
    available_at: datetime
    credited_at: datetime | None

    class Config:
        from_attributes = True


class StructureLevelInfo(BaseModel):
    level: int
    count: int


class StructureSummaryResponse(BaseModel):
    referral_code: str
    referral_link: str
    total: int
    levels: list[StructureLevelInfo]


class StructureMemberInfo(BaseModel):
    id: int
    # Приватность: имя + первая буква фамилии («Иван П.»), без телефона.
    name: str
    joined_at: datetime
    structure_count: int
    status: str


class StructureListResponse(BaseModel):
    levels: dict[int, list[StructureMemberInfo]]


class AccrueRequest(BaseModel):
    base_amount: Decimal = Field(..., gt=0, description="Базовая сумма доходного события")


class RequestSmsCodeRequest(BaseModel):
    phone: str = Field(..., min_length=10, max_length=20, description="Phone number")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        digits_only = "".join(c for c in v if c.isdigit())
        if len(digits_only) < 10:
            raise ValueError("Phone must contain at least 10 digits")
        return digits_only


class RegisterRequest(BaseModel):

    phone: str = Field(..., min_length=10, max_length=20, description="Phone number")
    code: str = Field(..., min_length=6, max_length=6, description="SMS verification code")
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=8, max_length=128, description="Password")
    first_name: str | None = Field(None, max_length=100, description="First name")
    last_name: str | None = Field(None, max_length=100, description="Last name")
    patronymic: str | None = Field(None, max_length=100, description="Patronymic")
    referral_code: str = Field(
        ..., min_length=4, max_length=16, description="Реферальный код пригласившего"
    )

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        digits_only = "".join(c for c in v if c.isdigit())
        if len(digits_only) < 10:
            raise ValueError("Phone must contain at least 10 digits")
        return digits_only

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class LoginWithCodeRequest(BaseModel):
    phone: str = Field(..., min_length=10, max_length=20, description="Phone number")
    code: str = Field(..., min_length=6, max_length=6, description="SMS verification code")
    password: str = Field(..., min_length=8, max_length=128, description="Password")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        digits_only = "".join(c for c in v if c.isdigit())
        if len(digits_only) < 10:
            raise ValueError("Phone must contain at least 10 digits")
        return digits_only


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class RefreshTokenRequest(BaseModel):
    refresh_token: str
