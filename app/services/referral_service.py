"""Сервис реферальной системы.

Поддерживает 4 уровня апплайна. Проценты вознаграждений читаются из
глобальных настроек платформы (``settings.bonus_level_{1..4}_percent``),
как и задержка доступности (``bonus_accrual_delay_days``) и правило для
заблокированных рефереров (``blocked_user_level_rule``):

- ``skip`` — заблокированный уровень ничего не получает, подъём по цепочке
  продолжается (уровни выше получают свои обычные проценты);
- ``zero`` — заблокированный уровень получает 0 и подъём прекращается.

Все начисления сначала попадают в ``users.pending_balance``. После
наступления ``available_at`` они переносятся в ``balance`` методом
:meth:`process_matured_accruals` (его дергает и фоновая задача).

Цепочка из 4 рефереров вверх кешируется в Redis (TTL 1 час). В кеше лежат
только id — статусы пользователей всегда читаются из БД в момент
начисления, поэтому блокировка реферера не делает кеш некорректным.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.settings import PlatformSettings
from app.models.users.entities import User
from app.models.users.referral import ReferralAccrual
from app.services.notification_service import NotificationService
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)

UPLINE_CACHE_TTL_SECONDS = 3600


@dataclass
class StructureMember:
    user: User
    structure_count: int


class ReferralService:
    MAX_LEVELS: int = 4

    def __init__(self, session: AsyncSession, redis=None) -> None:
        self._session = session
        self._redis = redis
        self._settings_service = SettingsService(session, redis)

    @staticmethod
    def _quantize(amount: Decimal) -> Decimal:
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def _upline_cache_key(user_id: int) -> str:
        return f"referral:upline:{user_id}"

    def build_referral_link(self, code: str) -> str:
        return f"{settings.referral_link_base_url.rstrip('/')}/{code}"

    async def get_upline_ids(self, user: User) -> list[int]:
        """id до 4 рефереров вверх (уровень 1 — первый элемент), через Redis-кеш."""
        key = self._upline_cache_key(user.id)
        if self._redis is not None:
            try:
                cached = await self._redis.get(key)
                if cached:
                    return [int(uid) for uid in json.loads(cached)]
            except Exception:
                logger.warning("Upline cache read failed", exc_info=True)

        upline: list[int] = []
        current_id = user.referrer_id
        while current_id is not None and len(upline) < self.MAX_LEVELS:
            upline.append(current_id)
            referrer = await self._session.get(User, current_id)
            current_id = referrer.referrer_id if referrer is not None else None

        if self._redis is not None:
            try:
                await self._redis.set(
                    key, json.dumps(upline), ex=UPLINE_CACHE_TTL_SECONDS
                )
            except Exception:
                logger.warning("Upline cache write failed", exc_info=True)
        return upline

    async def invalidate_upline_cache(self, user_id: int) -> None:
        """Сброс кеша цепочки при изменении реферального дерева
        (регистрация, блокировка/удаление реферера)."""
        if self._redis is None:
            return
        try:
            await self._redis.delete(self._upline_cache_key(user_id))
        except Exception:
            logger.warning("Upline cache invalidation failed", exc_info=True)

    @classmethod
    def _level_percents(cls, platform: dict) -> list[Decimal]:
        """Доли (0.03 = 3%) по уровням 1..4 из настроек платформы."""
        return [
            Decimal(str(platform[f"bonus_level_{level}_percent"])) / Decimal("100")
            for level in range(1, cls.MAX_LEVELS + 1)
        ]

    async def accrue_for_source(
        self, source_user: User, base_amount: Decimal
    ) -> list[ReferralAccrual]:
        if base_amount <= 0:
            raise ValueError("base_amount must be positive")

        platform = await self._settings_service.get_values()
        percents = self._level_percents(platform)
        blocked_rule = platform["blocked_user_level_rule"]
        available_at = datetime.utcnow() + timedelta(
            days=int(platform["bonus_accrual_delay_days"])
        )

        accruals: list[ReferralAccrual] = []
        upline_ids = await self.get_upline_ids(source_user)
        for level_idx, referrer_id in enumerate(upline_ids):
            referrer = await self._session.get(User, referrer_id)
            if referrer is None:
                break

            if referrer.status != User.STATUS_ACTIVE:
                if blocked_rule == PlatformSettings.BLOCKED_RULE_ZERO:
                    break  # уровень получает 0, выше не поднимаемся
                continue  # skip: уровень пропускается, идём дальше вверх

            level = level_idx + 1
            percent = percents[level_idx]
            amount = self._quantize(base_amount * percent)

            is_owner = referrer.referrer_id is None
            if amount > 0 and not is_owner:
                accrual = ReferralAccrual(
                    user_id=referrer.id,
                    source_user_id=source_user.id,
                    level=level,
                    percent=percent,
                    base_amount=self._quantize(base_amount),
                    amount=amount,
                    status=ReferralAccrual.STATUS_PENDING,
                    available_at=available_at,
                )
                self._session.add(accrual)
                referrer.pending_balance = self._quantize(
                    (referrer.pending_balance or Decimal("0")) + amount
                )
                accruals.append(accrual)

        await self._session.commit()
        for accrual in accruals:
            await self._session.refresh(accrual)
        return accruals

    async def process_matured_accruals(
        self, user_id: int | None = None
    ) -> list[ReferralAccrual]:
        """Перенос созревших начислений из pending_balance в balance.

        Вызывается и вручную (эндпоинт), и фоновой задачей раз в час.
        Каждому получателю ставится в очередь SMS ``bonus_accrued``
        с суммарной суммой за проход.
        """
        now = datetime.utcnow()
        stmt = select(ReferralAccrual).where(
            ReferralAccrual.status == ReferralAccrual.STATUS_PENDING,
            ReferralAccrual.available_at <= now,
        )
        if user_id is not None:
            stmt = stmt.where(ReferralAccrual.user_id == user_id)

        result = await self._session.execute(stmt)
        matured = list(result.scalars().all())
        if not matured:
            return []

        # Группируем суммы по получателю, чтобы делать минимум обращений.
        per_user: dict[int, Decimal] = {}
        for accrual in matured:
            per_user[accrual.user_id] = per_user.get(
                accrual.user_id, Decimal("0")
            ) + accrual.amount

        notifications = NotificationService(self._session)
        for uid, total in per_user.items():
            user = await self._session.get(User, uid)
            if user is None:
                continue
            user.balance = self._quantize((user.balance or Decimal("0")) + total)
            user.pending_balance = self._quantize(
                (user.pending_balance or Decimal("0")) - total
            )
            if user.pending_balance < 0:
                user.pending_balance = Decimal("0")
            await notifications.send(uid, "bonus_accrued", {"amount": str(total)})

        for accrual in matured:
            accrual.status = ReferralAccrual.STATUS_CREDITED
            accrual.credited_at = now

        await self._session.commit()
        for accrual in matured:
            await self._session.refresh(accrual)
        return matured

    async def get_structure_summary(self, user: User) -> dict:
        levels: list[dict] = []
        total = 0
        current_ids: list[int] = [user.id]
        for level in range(1, self.MAX_LEVELS + 1):
            if not current_ids:
                levels.append({"level": level, "count": 0})
                continue
            result = await self._session.execute(
                select(User.id).where(User.referrer_id.in_(current_ids))
            )
            next_ids = [row[0] for row in result.all()]
            levels.append({"level": level, "count": len(next_ids)})
            total += len(next_ids)
            current_ids = next_ids

        return {
            "referral_code": user.referral_code,
            "referral_link": self.build_referral_link(user.referral_code),
            "total": total,
            "levels": levels,
        }

    async def get_structure_list(self, user: User) -> dict[int, list[StructureMember]]:
        """Участники структуры по уровням 1..4 с размером их собственной структуры.

        Размер структуры участника — все его потомки на 4 уровня вниз от него,
        поэтому обход идёт до глубины 8 (участник 4-го уровня + его 4 уровня),
        но в выдачу попадают только уровни 1..4.
        """
        levels: dict[int, list[User]] = {lvl: [] for lvl in range(1, self.MAX_LEVELS + 1)}
        parent: dict[int, int | None] = {}
        depth_of: dict[int, int] = {}

        current_ids: list[int] = [user.id]
        for depth in range(1, self.MAX_LEVELS * 2 + 1):
            if not current_ids:
                break
            result = await self._session.execute(
                select(User).where(User.referrer_id.in_(current_ids))
            )
            members = list(result.scalars().all())
            for m in members:
                parent[m.id] = m.referrer_id
                depth_of[m.id] = depth
            if depth <= self.MAX_LEVELS:
                levels[depth] = members
            current_ids = [m.id for m in members]

        # Каждый найденный узел добавляет +1 всем предкам не дальше 4 уровней вверх.
        counts: dict[int, int] = {uid: 0 for uid in parent}
        for uid, depth in depth_of.items():
            ancestor = parent.get(uid)
            steps = 1
            while ancestor is not None and steps <= self.MAX_LEVELS:
                if ancestor in counts:
                    counts[ancestor] += 1
                ancestor = parent.get(ancestor)
                steps += 1

        return {
            lvl: [StructureMember(user=m, structure_count=counts.get(m.id, 0)) for m in members]
            for lvl, members in levels.items()
        }

    async def list_accruals(
        self, user_id: int, status: str | None = None
    ) -> list[ReferralAccrual]:
        stmt = select(ReferralAccrual).where(ReferralAccrual.user_id == user_id)
        if status:
            stmt = stmt.where(ReferralAccrual.status == status)
        stmt = stmt.order_by(ReferralAccrual.created_at.desc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
