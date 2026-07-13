import logging
import secrets
from datetime import datetime, timedelta

from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.users.dto import (
    LoginWithCodeRequest,
    RefreshTokenRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.models.users.entities import User
from app.models.users.refresh_token import RefreshToken
from app.services.code_generator_service import CodeManager
from app.services.notification_service import NotificationService
from app.services.referral_service import ReferralService
from app.services.errors import (
    ReferralLinkInvalidError,
    SmsRateLimitError,
    UserBlockedError,
)
from app.services.settings_service import SettingsService
from app.services.sms_service import SMSService_SMSC

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
logger = logging.getLogger(__name__)

SMS_DAILY_COUNTER_TTL = 24 * 60 * 60


class AuthService:
    def __init__(self, session: AsyncSession, redis=None):
        self._session = session
        self._redis = redis
        self._code_manager = CodeManager(redis) if redis is not None else None
        self._settings_service = SettingsService(session, redis)

    def _hash_password(self, password: str) -> str:
        return pwd_context.hash(password)

    def _verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return pwd_context.verify(plain_password, hashed_password)

    def _generate_access_token(self, user_id: int) -> str:
        payload = {
            "user_id": user_id,
            "sub": f"user:{user_id}",
            "role": "user",
            "type": "access",
            "exp": datetime.utcnow()
            + timedelta(minutes=settings.jwt_access_token_expire_minutes),
            "iat": datetime.utcnow(),
        }
        return jwt.encode(
            payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
        )

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
        expires_at = datetime.utcnow() + timedelta(
            days=settings.jwt_refresh_token_expire_days
        )

        refresh_token = RefreshToken(
            token=token,
            user_id=user_id,
            expires_at=expires_at,
        )

        self._session.add(refresh_token)
        await self._session.commit()
        await self._session.refresh(refresh_token)

        return refresh_token

    def _require_code_manager(self) -> CodeManager:
        if self._code_manager is None:
            raise RuntimeError("Redis is not available: SMS codes cannot be processed")
        return self._code_manager

    async def _verify_sms_code(self, phone: str, code: str) -> bool:
        is_valid = await self._require_code_manager().verify_code(phone, code)
        logger.info("SMS code verification for %s -> %s", phone, is_valid)
        return is_valid

    async def _enforce_sms_daily_limit(self, phone: str) -> None:
        platform = await self._settings_service.get_values()
        limit = int(platform.get("sms_daily_limit_per_user") or 0)
        if limit <= 0:
            return
        key = f"sms_daily:{phone}"
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, SMS_DAILY_COUNTER_TTL)
        if count > limit:
            raise SmsRateLimitError(limit)

    async def request_sms_code(self, phone: str) -> None:
        code_manager = self._require_code_manager()
        await self._enforce_sms_daily_limit(phone)

        code = await code_manager.new_code(phone)

        if settings.smsc_login and settings.smsc_password:
            platform = await self._settings_service.get_values()
            sms_service = SMSService_SMSC.with_credentials(
                username=settings.smsc_login,
                password=settings.smsc_password,
                lk_url=settings.sms_lk_url,
                sender=platform.get("sms_sender_id") or None,
            )
            try:
                await sms_service.send_sms(phone, code)
            except Exception:
                # Код уже лежит в Redis; не раскрываем его в ошибке.
                logger.exception("Failed to send SMS to %s", phone)
                raise RuntimeError("Failed to send SMS")
        else:
            # Dev-режим: SMSC не сконфигурирован, код только в логе.
            logger.info("SMSC is not configured; code for %s: %s", phone, code)

    async def _ensure_phone_unique(self, phone: str) -> None:
        result = await self._session.execute(select(User).where(User.phone == phone))
        if result.scalar_one_or_none() is not None:
            raise ValueError("Phone number already registered")

    async def _resolve_referrer_id(self, referral_code: str) -> int | None:
        """id реферера, либо None для корневого кода.

        Регистрация возможна только по действующей ссылке: несуществующий код
        или заблокированный/удалённый реферер → ReferralLinkInvalidError.
        """
        platform = await self._settings_service.get_values()
        root_code = platform.get("root_referral_code")
        if (
            root_code
            and platform.get("root_referral_active")
            and referral_code == root_code
        ):
            return None

        ref_result = await self._session.execute(
            select(User).where(User.referral_code == referral_code)
        )
        referrer = ref_result.scalar_one_or_none()
        if referrer is None or referrer.status != User.STATUS_ACTIVE:
            raise ReferralLinkInvalidError()
        return referrer.id

    async def register(self, data: RegisterRequest) -> TokenResponse:
        if not await self._verify_sms_code(data.phone, data.code):
            raise ValueError("Invalid or expired verification code")

        await self._ensure_phone_unique(data.phone)

        referrer_id = await self._resolve_referrer_id(data.referral_code)

        user = User(
            email=data.email,
            phone=data.phone,
            password_hash=self._hash_password(data.password),
            first_name=data.first_name,
            last_name=data.last_name,
            patronymic=data.patronymic,
            referral_code=await self._generate_unique_referral_code(),
            referrer_id=referrer_id,
        )

        self._session.add(user)
        await self._session.commit()
        await self._session.refresh(user)

        # Приветственное SMS уходит через очередь (фоновая задача sms_job).
        await NotificationService(self._session).send(
            user.id, "registration_welcome", {"referral_code": user.referral_code}
        )
        await self._session.commit()
        # Дерево изменилось — сбрасываем кеш цепочки нового пользователя.
        await ReferralService(self._session, self._redis).invalidate_upline_cache(
            user.id
        )

        access_token = self._generate_access_token(user.id)
        refresh_token = await self._create_refresh_token(user.id)

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token.token,
            user=UserResponse.model_validate(user),
        )

    async def login(self, data: LoginWithCodeRequest) -> TokenResponse:
        if not await self._verify_sms_code(data.phone, data.code):
            raise ValueError("Invalid or expired verification code")

        result = await self._session.execute(
            select(User).where(User.phone == data.phone)
        )
        user = result.scalar_one_or_none()

        if not user or user.status == User.STATUS_DELETED:
            raise ValueError("User not found")

        if not self._verify_password(data.password, user.password_hash):
            raise ValueError("Invalid password")

        if user.status == User.STATUS_BLOCKED:
            raise UserBlockedError(
                reason=user.blocked_reason, comment=user.blocked_comment
            )

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

        if user.status == User.STATUS_BLOCKED:
            raise UserBlockedError(
                reason=user.blocked_reason, comment=user.blocked_comment
            )
        if user.status == User.STATUS_DELETED:
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
