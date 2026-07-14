"""Чтение/обновление глобальных настроек платформы (таблица ``settings``).

Единственная строка (id=1) создаётся лениво с дефолтами из модели.
Чтение идёт через Redis-кеш (TTL 5 минут); при недоступном Redis
сервис прозрачно работает напрямую с БД.
"""
from __future__ import annotations

import json
import logging
import secrets
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import PlatformSettings

logger = logging.getLogger(__name__)

CACHE_KEY = "settings:platform"
CACHE_TTL_SECONDS = 300

_DECIMAL_FIELDS = (
    "bonus_level_1_percent",
    "bonus_level_2_percent",
    "bonus_level_3_percent",
    "bonus_level_4_percent",
    "bonus_min_exchange",
)
_INT_FIELDS = ("bonus_accrual_delay_days", "sms_daily_limit_per_user")
_BOOL_FIELDS = ("root_referral_active",)
_STR_FIELDS = ("blocked_user_level_rule", "sms_provider", "sms_sender_id")
_NULLABLE_STR_FIELDS = ("root_referral_code",)
_DICT_FIELDS = ("sms_templates",)

EDITABLE_FIELDS = (
    _DECIMAL_FIELDS
    + _INT_FIELDS
    + _BOOL_FIELDS
    + _STR_FIELDS
    + _NULLABLE_STR_FIELDS
    + _DICT_FIELDS
)


class SettingsService:
    def __init__(self, session: AsyncSession, redis=None):
        self._session = session
        self._redis = redis

    @staticmethod
    def as_dict(row: PlatformSettings) -> dict[str, Any]:
        """JSON-безопасный словарь настроек (Decimal → str)."""
        out: dict[str, Any] = {}
        for f in _DECIMAL_FIELDS:
            out[f] = str(getattr(row, f))
        for f in _INT_FIELDS + _BOOL_FIELDS + _STR_FIELDS + _NULLABLE_STR_FIELDS:
            out[f] = getattr(row, f)
        for f in _DICT_FIELDS:
            out[f] = dict(getattr(row, f) or {})
        return out

    @staticmethod
    def _typed(values: dict[str, Any]) -> dict[str, Any]:
        typed = dict(values)
        for f in _DECIMAL_FIELDS:
            if typed.get(f) is not None:
                typed[f] = Decimal(str(typed[f]))
        return typed

    async def get(self) -> PlatformSettings:
        """Строка настроек из БД; создаётся с дефолтами при первом обращении."""
        row = await self._session.get(PlatformSettings, PlatformSettings.SINGLETON_ID)
        if row is None:
            row = PlatformSettings(id=PlatformSettings.SINGLETON_ID)
            self._session.add(row)
            await self._session.flush()
        return row

    async def get_values(self) -> dict[str, Any]:
        """Типизированные значения настроек, через Redis-кеш когда он доступен."""
        if self._redis is not None:
            try:
                cached = await self._redis.get(CACHE_KEY)
                if cached:
                    return self._typed(json.loads(cached))
            except Exception:
                logger.warning("Settings cache read failed, falling back to DB", exc_info=True)

        row = await self.get()
        raw = self.as_dict(row)

        if self._redis is not None:
            try:
                await self._redis.set(CACHE_KEY, json.dumps(raw), ex=CACHE_TTL_SECONDS)
            except Exception:
                logger.warning("Settings cache write failed", exc_info=True)

        return self._typed(raw)

    async def invalidate_cache(self) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.delete(CACHE_KEY)
        except Exception:
            logger.warning("Settings cache invalidation failed", exc_info=True)

    async def update(self, changes: dict[str, Any]) -> PlatformSettings:
        unknown = set(changes) - set(EDITABLE_FIELDS)
        if unknown:
            raise ValueError(f"Unknown settings fields: {', '.join(sorted(unknown))}")

        rule = changes.get("blocked_user_level_rule")
        if rule is not None and rule not in PlatformSettings.BLOCKED_RULES:
            raise ValueError(
                f"blocked_user_level_rule must be one of {PlatformSettings.BLOCKED_RULES}"
            )

        templates = changes.get("sms_templates")
        if templates is not None:
            if not isinstance(templates, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in templates.items()
            ):
                raise ValueError("sms_templates must be a dict of str -> str")

        row = await self.get()
        for field, value in changes.items():
            if field in _DECIMAL_FIELDS and value is not None:
                value = Decimal(str(value))
            setattr(row, field, value)

        await self._session.commit()
        await self._session.refresh(row)
        await self.invalidate_cache()
        return row

    async def generate_root_referral(self) -> PlatformSettings:
        """Выпустить корневой реферальный код и активировать его."""
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        # 12 символов против 8 у пользовательских кодов — коллизии исключены.
        code = "".join(secrets.choice(alphabet) for _ in range(12))
        return await self.update(
            {"root_referral_code": code, "root_referral_active": True}
        )

    async def revoke_root_referral(self) -> PlatformSettings:
        return await self.update(
            {"root_referral_code": None, "root_referral_active": False}
        )
