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
    email: str
    phone: str
    first_name: str | None
    last_name: str | None
    patronymic: str | None

    class Config:
        from_attributes = True


class RequestSmsCodeRequest(BaseModel):
    phone: str = Field(..., min_length=10, max_length=20, description="Phone number")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        digits_only = "".join(c for c in v if c.isdigit())
        if len(digits_only) < 10:
            raise ValueError("Phone must contain at least 10 digits")
        return digits_only


class RegisterWithCodeRequest(BaseModel):
    phone: str = Field(..., min_length=10, max_length=20, description="Phone number")
    code: str = Field(..., min_length=6, max_length=6, description="SMS verification code")
    email: EmailStr = Field(..., description="User email address")
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
