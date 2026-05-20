from datetime import datetime, timedelta

from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.dto.support_agent import SupportTokenResponse
from app.models.tables.support_agent import SupportAgent


_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


class SupportAuthService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def login(self, login: str, password: str) -> SupportTokenResponse:
        row = await self._session.execute(select(SupportAgent).where(SupportAgent.login == login))
        agent = row.scalar_one_or_none()
        if agent is None or not agent.is_active:
            raise ValueError("invalid credentials")
        if not _pwd.verify(password, agent.password_hash):
            raise ValueError("invalid credentials")

        expires = settings.jwt_access_token_expire_minutes * 60
        now = datetime.utcnow()
        payload = {
            "sub": f"support:{agent.id}",
            "role": "support",
            "subject_type": "support",
            "subject_id": agent.id,
            "type": "access",
            "exp": now + timedelta(seconds=expires),
            "iat": now,
        }
        token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
        return SupportTokenResponse(access_token=token, token_type="bearer", expires_in=expires)
