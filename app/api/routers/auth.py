from fastapi import APIRouter, status, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.redis_dep import get_redis
from app.core.database import get_async_session
from app.services.auth_service import AuthService
from app.services.code_generator_service import AttemptsError
from app.services.errors import SmsRateLimitError, UserBlockedError
from app.models.users.dto import (
    RequestSmsCodeRequest,
    RegisterRequest,
    LoginWithCodeRequest,
    TokenResponse,
    RefreshTokenRequest,
)


router = APIRouter(prefix="/auth", tags=["auth"])


def _blocked_exception(e: UserBlockedError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "message": "Аккаунт заблокирован",
            "reason": e.reason,
            "comment": e.comment,
        },
    )


@router.post("/request-code/", status_code=status.HTTP_202_ACCEPTED)
async def request_sms_code(
    data: RequestSmsCodeRequest,
    session: AsyncSession = Depends(get_async_session),
    redis=Depends(get_redis),
) -> dict[str, str]:
    auth_service = AuthService(session, redis)
    try:
        await auth_service.request_sms_code(data.phone)
    except SmsRateLimitError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SMS service is temporarily unavailable",
        )
    return {"message": "SMS code sent"}


@router.post("/register/", status_code=status.HTTP_201_CREATED)
async def register(
    data: RegisterRequest,
    session: AsyncSession = Depends(get_async_session),
    redis=Depends(get_redis),
) -> TokenResponse:
    auth_service = AuthService(session, redis)
    try:
        return await auth_service.register(data)
    except AttemptsError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Превышен лимит попыток ввода кода",
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SMS service is temporarily unavailable",
        )


@router.post("/login/", status_code=status.HTTP_200_OK)
async def login(
    data: LoginWithCodeRequest,
    session: AsyncSession = Depends(get_async_session),
    redis=Depends(get_redis),
) -> TokenResponse:
    auth_service = AuthService(session, redis)
    try:
        return await auth_service.login(data)
    except UserBlockedError as e:
        raise _blocked_exception(e)
    except AttemptsError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Превышен лимит попыток ввода кода",
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SMS service is temporarily unavailable",
        )


@router.get("/debug-code/", include_in_schema=False)
async def debug_code(phone: str, redis=Depends(get_redis)) -> dict:
    """Dev-only helper: read the current OTP for a phone from Redis.
    Enabled only outside production so the local frontend can show the code."""
    from app.core.config import settings
    if settings.environment == "production":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    import json
    digits = "".join(c for c in phone if c.isdigit())
    raw = await redis.get(f"otp:{digits}")
    if not raw:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no code")
    return {"code": json.loads(raw)["code"]}


@router.post("/refresh/", status_code=status.HTTP_200_OK)
async def refresh_token(
    data: RefreshTokenRequest,
    session: AsyncSession = Depends(get_async_session),
) -> TokenResponse:
    auth_service = AuthService(session)
    try:
        return await auth_service.refresh(data)
    except UserBlockedError as e:
        raise _blocked_exception(e)
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
