from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.models.dto.support_agent import SupportLoginRequest, SupportTokenResponse
from app.services.support_auth_service import SupportAuthService


router = APIRouter(prefix="/support", tags=["support"])


@router.post("/login/", response_model=SupportTokenResponse)
async def support_login(
    payload: SupportLoginRequest,
    session: AsyncSession = Depends(get_async_session),
) -> SupportTokenResponse:
    svc = SupportAuthService(session)
    try:
        return await svc.login(payload.login, payload.password)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
