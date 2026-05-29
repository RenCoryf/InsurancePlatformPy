
from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.users.bonus import BonusWithdrawalRequest
from app.models.users.entities import User


class BonusService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _quantize(amount: Decimal) -> Decimal:
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

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
