from datetime import datetime

from pydantic import BaseModel, Field


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


class SupportAgentResponse(BaseModel):
    id: int
    login: str
    display_name: str
    is_active: bool
    created_at: datetime
