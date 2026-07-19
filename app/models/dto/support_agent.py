from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.tables.support_agent import SupportAgent


def _validate_permissions(perms: list[str]) -> list[str]:
    unknown = set(perms) - set(SupportAgent.ALLOWED_PERMISSIONS)
    if unknown:
        raise ValueError(f"unknown permissions: {', '.join(sorted(unknown))}")
    return list(dict.fromkeys(perms))  # dedup, порядок сохраняем


class SupportLoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class SupportTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class SupportAgentCreate(BaseModel):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(min_length=1, max_length=100)


class SupportAgentUpdate(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=200)
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None
    permissions: list[str] | None = None

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return _validate_permissions(v)


class SupportAgentResponse(BaseModel):
    id: int
    login: str
    display_name: str
    is_active: bool
    role: str = SupportAgent.ROLE_MANAGER
    permissions: list[str] = []
    phone: str | None = None
    is_owner: bool = False
    created_at: datetime


class ManagerCreateRequest(BaseModel):
    """Создание менеджера/администратора с приглашением по SMS."""

    login: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=100)
    phone: str = Field(min_length=10, max_length=20)
    role: str = SupportAgent.ROLE_MANAGER
    permissions: list[str] = []

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        digits_only = "".join(c for c in v if c.isdigit())
        if len(digits_only) < 10:
            raise ValueError("Phone must contain at least 10 digits")
        return digits_only

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in SupportAgent.ROLES:
            raise ValueError(f"role must be one of {SupportAgent.ROLES}")
        return v

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, v: list[str]) -> list[str]:
        return _validate_permissions(v)


class ManagerInviteResponse(BaseModel):
    agent: SupportAgentResponse
    invite_token: str
    invite_expires_at: datetime
    invite_link: str


class InviteAcceptRequest(BaseModel):
    token: str = Field(min_length=16, max_length=64)
    password: str = Field(min_length=8, max_length=200)
