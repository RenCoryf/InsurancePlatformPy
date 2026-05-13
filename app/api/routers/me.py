from fastapi import APIRouter, status, Depends
from pydantic import BaseModel, Field

from app.api.dependencies import get_current_user
from app.models.users.entities import User
from app.models.users.dto import UserResponse


class MeUpdate(BaseModel):
    first_name: str | None = Field(None, max_length=100)
    last_name: str | None = Field(None, max_length=100)
    email: str | None = Field(None)


router = APIRouter(prefix="/me", tags=["me"])


@router.get("/", response_model=UserResponse)
async def get_profile(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.patch("/", response_model=UserResponse)
async def update_profile(
    payload: MeUpdate, current_user: User = Depends(get_current_user)
) -> UserResponse:
    if payload.first_name is not None:
        current_user.first_name = payload.first_name
    if payload.last_name is not None:
        current_user.last_name = payload.last_name
    if payload.email is not None:
        current_user.email = payload.email
    
    return UserResponse.model_validate(current_user)
