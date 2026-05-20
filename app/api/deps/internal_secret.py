import secrets

from fastapi import Header, HTTPException, status

from app.core.config import settings


async def internal_secret_required(
    x_internal_secret: str = Header(default="", alias="X-Internal-Secret"),
) -> None:
    expected = settings.internal_secret
    if not expected:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal secret not configured")
    if not secrets.compare_digest(x_internal_secret, expected):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
