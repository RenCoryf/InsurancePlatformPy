
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.users.entities import User
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService


class BonusService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _quantize(amount: Decimal) -> Decimal:
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    async def debit(
        self,
        user_id: int,
        amount: Decimal,
        reason: str,
        performed_by: int | None = None,
        *,
        commit: bool = True,
    ) -> User:
        """Списать бонусы с доступного баланса (менеджер/система).

        ``commit=False`` — списание фиксируется транзакцией вызывающего кода
        (например, завершением заявки на сертификат).
        """
        if amount <= 0:
            raise ValueError("amount must be positive")
        amount = self._quantize(amount)

        user = await self._session.get(User, user_id)
        if user is None:
            raise ValueError("user not found")
        if (user.balance or Decimal("0")) < amount:
            raise ValueError("insufficient balance")

        user.balance = self._quantize((user.balance or Decimal("0")) - amount)

        await AuditService(self._session).log(
            performed_by_type=AuditLog.BY_MANAGER if performed_by else AuditLog.BY_SYSTEM,
            performed_by_id=performed_by,
            action=AuditLog.ACTION_BONUS_MANUAL_DEBIT,
            target_type=AuditLog.TARGET_BONUS,
            target_id=str(user_id),
            new_value={"amount": str(amount), "reason": reason},
            comment=reason,
        )

        if commit:
            await self._session.commit()
            await self._session.refresh(user)
        return user

    async def credit(
        self,
        user_id: int,
        amount: Decimal,
        reason: str,
        performed_by: int | None = None,
        *,
        commit: bool = True,
    ) -> User:
        """Начислить бонусы вручную (админ) с SMS-уведомлением."""
        if amount <= 0:
            raise ValueError("amount must be positive")
        amount = self._quantize(amount)

        user = await self._session.get(User, user_id)
        if user is None:
            raise ValueError("user not found")

        user.balance = self._quantize((user.balance or Decimal("0")) + amount)

        await AuditService(self._session).log(
            performed_by_type=AuditLog.BY_ADMIN,
            performed_by_id=performed_by,
            action=AuditLog.ACTION_BONUS_MANUAL_CREDIT,
            target_type=AuditLog.TARGET_BONUS,
            target_id=str(user_id),
            new_value={"amount": str(amount), "reason": reason},
            comment=reason,
        )

        await NotificationService(self._session).send(
            user_id,
            "bonus_manual_credit",
            {"amount": str(amount), "reason": reason},
        )

        if commit:
            await self._session.commit()
            await self._session.refresh(user)
        return user
