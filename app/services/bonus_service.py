
from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.users.bonus import BonusWithdrawalRequest
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

    async def create_withdrawal(
        self, user: User, amount: Decimal, comment: str | None = None
    ) -> BonusWithdrawalRequest:
        if amount <= 0:
            raise ValueError("amount must be positive")

        amount = self._quantize(amount)
        if (user.balance or Decimal("0")) < amount:
            raise ValueError("insufficient balance")

        user.balance = self._quantize(
            (user.balance or Decimal("0")) - amount
        )

        request = BonusWithdrawalRequest(
            user_id=user.id,
            amount=amount,
            status=BonusWithdrawalRequest.STATUS_PENDING,
            comment=comment,
        )
        self._session.add(request)
        await self._session.commit()
        await self._session.refresh(request)

        return request

    async def approve(self, request_id: int) -> BonusWithdrawalRequest:
        request = await self._session.get(BonusWithdrawalRequest, request_id)
        if request is None:
            raise ValueError("request not found")
        if request.status != BonusWithdrawalRequest.STATUS_PENDING:
            raise ValueError("request is not pending")

        request.status = BonusWithdrawalRequest.STATUS_APPROVED
        request.processed_at = datetime.utcnow()

        await self._session.commit()
        await self._session.refresh(request)
        return request

    async def reject(self, request_id: int) -> BonusWithdrawalRequest:
        request = await self._session.get(BonusWithdrawalRequest, request_id)
        if request is None:
            raise ValueError("request not found")
        if request.status != BonusWithdrawalRequest.STATUS_PENDING:
            raise ValueError("request is not pending")

        user = await self._session.get(User, request.user_id)
        if user is None:
            raise ValueError("user not found")

        user.balance = self._quantize(
            (user.balance or Decimal("0")) + request.amount
        )
        request.status = BonusWithdrawalRequest.STATUS_REJECTED
        request.processed_at = datetime.utcnow()

        await self._session.commit()
        await self._session.refresh(request)
        return request

    async def list_user_history(
        self, user_id: int, status: str | None = None
    ) -> list[BonusWithdrawalRequest]:
        stmt = select(BonusWithdrawalRequest).where(
            BonusWithdrawalRequest.user_id == user_id
        )
        if status:
            stmt = stmt.where(BonusWithdrawalRequest.status == status)
        stmt = stmt.order_by(BonusWithdrawalRequest.created_at.desc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
