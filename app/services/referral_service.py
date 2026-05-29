"""Сервис реферальной системы.

Поддерживает 5 уровней апплайна.
Проценты вознаграждений по уровням: 1 — 3%, 2 — 3%, 3 — 2%, 4 — 1%, 5+ — 0%.
Все начисления сначала попадают в ``users.pending_balance``. После истечения
``settings.referral_accrual_delay_days`` (по умолчанию 15 дней) они переносятся
из ``pending_balance`` в ``balance`` методом :meth:`process_matured_accruals`.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.users.entities import User
from app.models.users.referral import ReferralAccrual


class ReferralService:
    LEVEL_PERCENTS: list[Decimal] = [
        Decimal("0.03"),  # 1 уровень
        Decimal("0.03"),  # 2 уровень
        Decimal("0.02"),  # 3 уровень
        Decimal("0.01"),  # 4 уровень
        Decimal("0.00"),  # 5 уровень
    ]
    MAX_LEVELS: int = len(LEVEL_PERCENTS)

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _quantize(amount: Decimal) -> Decimal:
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def build_referral_link(self, code: str) -> str:
        return f"{settings.referral_link_base_url.rstrip('/')}/{code}"

    async def accrue_for_source(
        self, source_user: User, base_amount: Decimal
    ) -> list[ReferralAccrual]:
        if base_amount <= 0:
            raise ValueError("base_amount must be positive")

        accruals: list[ReferralAccrual] = []
        available_at = datetime.utcnow() + timedelta(
            days=settings.referral_accrual_delay_days
        )

        current_referrer_id = source_user.referrer_id
        for level_idx in range(self.MAX_LEVELS):
            if current_referrer_id is None:
                break
            referrer = await self._session.get(User, current_referrer_id)
            if referrer is None:
                break

            level = level_idx + 1
            percent = self.LEVEL_PERCENTS[level_idx]
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

            current_referrer_id = referrer.referrer_id

        await self._session.commit()
        for accrual in accruals:
            await self._session.refresh(accrual)
        return accruals

    async def process_matured_accruals(
        self, user_id: int | None = None
    ) -> list[ReferralAccrual]:
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

    async def get_structure_list(self, user: User) -> dict[int, list[User]]:
        levels: dict[int, list[User]] = {}
        current_ids: list[int] = [user.id]
        for level in range(1, self.MAX_LEVELS + 1):
            if not current_ids:
                levels[level] = []
                continue
            result = await self._session.execute(
                select(User).where(User.referrer_id.in_(current_ids))
            )
            members = list(result.scalars().all())
            levels[level] = members
            current_ids = [m.id for m in members]
        return levels

    async def list_accruals(
        self, user_id: int, status: str | None = None
    ) -> list[ReferralAccrual]:
        stmt = select(ReferralAccrual).where(ReferralAccrual.user_id == user_id)
        if status:
            stmt = stmt.where(ReferralAccrual.status == status)
        stmt = stmt.order_by(ReferralAccrual.created_at.desc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
