import logging
import secrets
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from passlib.context import CryptContext
from jose import jwt, JWTError

from app.models.users.dto import (
    RegisterRequest,
    LoginWithCodeRequest,
    TokenResponse,
    UserResponse,
    RefreshTokenRequest,
)
from app.models.users.entities import User
from app.models.users.refresh_token import RefreshToken
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
logger = logging.getLogger(__name__)


class AuthService:
    MOCK_SMS_CODE = "123456"

    def __init__(self, session: AsyncSession):
        self._session = session

    def _hash_password(self, password: str) -> str:
        return pwd_context.hash(password)

    def _verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return pwd_context.verify(plain_password, hashed_password)

    def _generate_access_token(self, user_id: int) -> str:
        payload = {
            "user_id": user_id,
            "type": "access",
            "exp": datetime.utcnow() + timedelta(minutes=settings.jwt_access_token_expire_minutes),
            "iat": datetime.utcnow(),
        }
        return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

    def _generate_refresh_token(self) -> str:
        return secrets.token_urlsafe(32)

    async def _generate_unique_referral_code(self, length: int = 8) -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        for _ in range(10):
            code = "".join(secrets.choice(alphabet) for _ in range(length))
            existing = await self._session.execute(
                select(User).where(User.referral_code == code)
            )
            if existing.scalar_one_or_none() is None:
                return code
        raise RuntimeError("Failed to generate unique referral code")

    async def _create_refresh_token(self, user_id: int) -> RefreshToken:
        token = self._generate_refresh_token()
        expires_at = datetime.utcnow() + timedelta(days=settings.jwt_refresh_token_expire_days)
        
        refresh_token = RefreshToken(
            token=token,
            user_id=user_id,
            expires_at=expires_at,
        )
        
        self._session.add(refresh_token)
        await self._session.commit()
        await self._session.refresh(refresh_token)
        
        return refresh_token

    def _verify_sms_code(self, code: str) -> bool:
        is_valid = code == self.MOCK_SMS_CODE
        logger.info(f"[MOCK SMS] Code verification: {code} -> {is_valid}")
        return is_valid

    async def request_sms_code(self, phone: str) -> None:
        logger.info(f"[MOCK SMS] Code sent to {phone}: {self.MOCK_SMS_CODE}")

    async def _ensure_phone_unique(self, phone: str) -> None:
        result = await self._session.execute(
            select(User).where(User.phone == phone)
        )
        if result.scalar_one_or_none() is not None:
            raise ValueError("Phone number already registered")

    async def register(self, data: RegisterRequest) -> TokenResponse:
        if not self._verify_sms_code(data.code):
            raise ValueError("Invalid or expired verification code")

        await self._ensure_phone_unique(data.phone)

        ref_result = await self._session.execute(
            select(User).where(User.referral_code == data.referral_code)
        )
        referrer = ref_result.scalar_one_or_none()
        if not referrer:
            raise ValueError("Invalid referral code")

        user = User(
            email=data.email,
            phone=data.phone,
            password_hash=self._hash_password(data.password),
            first_name=data.first_name,
            last_name=data.last_name,
            patronymic=data.patronymic,
            referral_code=await self._generate_unique_referral_code(),
            referrer_id=referrer.id,
        )

        self._session.add(user)
        await self._session.commit()
        await self._session.refresh(user)

        access_token = self._generate_access_token(user.id)
        refresh_token = await self._create_refresh_token(user.id)

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token.token,
            user=UserResponse.model_validate(user),
        )

    async def login(self, data: LoginWithCodeRequest) -> TokenResponse:
        if not self._verify_sms_code(data.code):
            raise ValueError("Invalid or expired verification code")

        result = await self._session.execute(
            select(User).where(User.phone == data.phone)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise ValueError("User not found")

        if not self._verify_password(data.password, user.password_hash):
            raise ValueError("Invalid password")

        access_token = self._generate_access_token(user.id)
        refresh_token = await self._create_refresh_token(user.id)

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token.token,
            user=UserResponse.model_validate(user),
        )

    async def refresh(self, data: RefreshTokenRequest) -> TokenResponse:
        result = await self._session.execute(
            select(RefreshToken).where(
                RefreshToken.token == data.refresh_token,
                RefreshToken.is_revoked == False,
            )
        )
        refresh_token = result.scalar_one_or_none()

        if not refresh_token:
            raise ValueError("Invalid refresh token")

        if refresh_token.expires_at < datetime.utcnow():
            raise ValueError("Refresh token expired")

        result = await self._session.execute(
            select(User).where(User.id == refresh_token.user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            raise ValueError("User not found")

        access_token = self._generate_access_token(user.id)
        new_refresh_token = await self._create_refresh_token(user.id)

        refresh_token.is_revoked = True
        await self._session.commit()

        return TokenResponse(
            access_token=access_token,
            refresh_token=new_refresh_token.token,
            user=UserResponse.model_validate(user),
        )

    async def logout(self, refresh_token_str: str) -> None:
        result = await self._session.execute(
            select(RefreshToken).where(RefreshToken.token == refresh_token_str)
        )
        refresh_token = result.scalar_one_or_none()

        if refresh_token:
            refresh_token.is_revoked = True
            await self._session.commit()
