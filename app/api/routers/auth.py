from fastapi import APIRouter, status, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.services.auth_service import AuthService
from app.models.users.dto import (
    RequestSmsCodeRequest,
    RegisterWithCodeRequest,
    LoginWithCodeRequest,
    TokenResponse,
    RefreshTokenRequest,
)


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/request-code/", status_code=status.HTTP_202_ACCEPTED)
async def request_sms_code(
    data: RequestSmsCodeRequest,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, str]:
    auth_service = AuthService(session)
    await auth_service.request_sms_code(data.phone)
    return {"message": "SMS code sent"}


@router.post("/register/", status_code=status.HTTP_201_CREATED)
async def register(
    data: RegisterWithCodeRequest,
    session: AsyncSession = Depends(get_async_session),
) -> TokenResponse:
    auth_service = AuthService(session)
    try:
        return await auth_service.register(data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/login/", status_code=status.HTTP_200_OK)
async def login(
    data: LoginWithCodeRequest,
    session: AsyncSession = Depends(get_async_session),
) -> TokenResponse:
    auth_service = AuthService(session)
    try:
        return await auth_service.login(data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/refresh/", status_code=status.HTTP_200_OK)
async def refresh_token(
    data: RefreshTokenRequest,
    session: AsyncSession = Depends(get_async_session),
) -> TokenResponse:
    auth_service = AuthService(session)
    try:
        return await auth_service.refresh(data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/logout/", status_code=status.HTTP_200_OK)
async def logout(
    data: RefreshTokenRequest,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, str]:
    auth_service = AuthService(session)
    try:
        await auth_service.logout(data.refresh_token)
        return {"message": "Successfully logged out"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
