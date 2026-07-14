"""Сделки (Deals) и начисление реферальных бонусов.

Сделку создаёт менеджер. Дата доступности бонусов ``accrual_date`` =
``policy_date`` + ``settings.bonus_accrual_delay_days``. Переход в статус
``policy_issued`` начисляет бонусы аплайну клиента (в pending_balance),
отмена выпущенного полиса (``rejected``/``error``) отменяет ещё не
зачисленные начисления. Всё в одной транзакции со сменой статуса.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.deals import Deal, DealStatusEvent
from app.models.users.entities import User
from app.services.application_service import validate_product, validate_status
from app.services.audit_service import AuditService
from app.services.referral_service import ReferralService
from app.services.settings_service import SettingsService


class DealService:
    def __init__(self, session: AsyncSession, redis=None):
        self._session = session
        self._redis = redis

    async def create(
        self,
        *,
        user_id: int,
        product: str,
        policy_amount: Decimal,
        policy_date: date,
        manager_id: int,
        application_id: UUID | None = None,
        comment: str | None = None,
    ) -> Deal:
        validate_product(product)
        if policy_amount <= 0:
            raise ValueError("policy_amount must be positive")

        user = await self._session.get(User, user_id)
        if user is None:
            raise ValueError("user not found")

        platform = await SettingsService(self._session, self._redis).get_values()
        accrual_date = policy_date + timedelta(
            days=int(platform["bonus_accrual_delay_days"])
        )

        deal = Deal(
            user_id=user_id,
            application_id=application_id,
            product=product,
            policy_amount=policy_amount,
            policy_date=policy_date,
            accrual_date=accrual_date,
            status=Deal.STATUS_NEW,
            assigned_manager_id=manager_id,
            comment=comment,
        )
        self._session.add(deal)
        await self._session.flush()

        await AuditService(self._session).log(
            performed_by_type=AuditLog.BY_MANAGER,
            performed_by_id=manager_id,
            action=AuditLog.ACTION_DEAL_CREATE,
            target_type=AuditLog.TARGET_DEAL,
            target_id=str(deal.id),
            new_value={
                "user_id": user_id,
                "product": product,
                "amount": str(policy_amount),
                "date": str(policy_date),
            },
            comment=comment,
        )

        await self._session.commit()
        await self._session.refresh(deal)
        return deal

    async def change_status(
        self,
        deal_id: UUID,
        new_status: str,
        manager_id: int,
        comment: str | None = None,
    ) -> Deal:
        """Смена статуса с логикой начисления/отмены бонусов."""
        validate_status(new_status)

        deal = await self._session.get(Deal, deal_id)
        if deal is None:
            raise ValueError("deal not found")

        old_status = deal.status
        if new_status == old_status:
            raise ValueError("deal is already in this status")

        deal.status = new_status
        deal.updated_at = datetime.utcnow()

        self._session.add(
            DealStatusEvent(
                deal_id=deal.id,
                old_status=old_status,
                new_status=new_status,
                changed_by_type=DealStatusEvent.BY_MANAGER,
                changed_by_id=manager_id,
                comment=comment,
            )
        )

        referrals = ReferralService(self._session, self._redis)
        if new_status == Deal.STATUS_POLICY_ISSUED:
            user = await self._session.get(User, deal.user_id)
            await referrals.accrue_for_source(
                user,
                deal.policy_amount,
                available_at=datetime.combine(deal.accrual_date, datetime.min.time()),
                deal_id=deal.id,
                commit=False,
            )
        elif (
            new_status in (Deal.STATUS_REJECTED, Deal.STATUS_ERROR)
            and old_status == Deal.STATUS_POLICY_ISSUED
        ):
            await referrals.cancel_pending_for_deal(deal.id)

        await AuditService(self._session).log(
            performed_by_type=AuditLog.BY_MANAGER,
            performed_by_id=manager_id,
            action=AuditLog.ACTION_DEAL_STATUS_CHANGE,
            target_type=AuditLog.TARGET_DEAL,
            target_id=str(deal.id),
            old_value={"status": old_status},
            new_value={"status": new_status},
            comment=comment,
        )

        await self._session.commit()
        await self._session.refresh(deal)
        return deal

    async def update_amount(
        self,
        deal_id: UUID,
        new_amount: Decimal,
        admin_id: int,
        reason: str,
    ) -> Deal:
        """Изменить сумму сделки (только admin)."""
        if new_amount <= 0:
            raise ValueError("new_amount must be positive")

        deal = await self._session.get(Deal, deal_id)
        if deal is None:
            raise ValueError("deal not found")

        old_amount = deal.policy_amount
        deal.policy_amount = new_amount
        deal.updated_at = datetime.utcnow()

        await AuditService(self._session).log(
            performed_by_type=AuditLog.BY_ADMIN,
            performed_by_id=admin_id,
            action=AuditLog.ACTION_DEAL_AMOUNT_CHANGE,
            target_type=AuditLog.TARGET_DEAL,
            target_id=str(deal.id),
            old_value={"amount": str(old_amount)},
            new_value={"amount": str(new_amount)},
            comment=reason,
        )

        await self._session.commit()
        await self._session.refresh(deal)
        return deal

    async def get(self, deal_id: UUID) -> Deal | None:
        return await self._session.get(Deal, deal_id)

    async def get_status_events(self, deal_id: UUID) -> list[DealStatusEvent]:
        result = await self._session.execute(
            select(DealStatusEvent)
            .where(DealStatusEvent.deal_id == deal_id)
            .order_by(DealStatusEvent.created_at, DealStatusEvent.id)
        )
        return list(result.scalars().all())

    async def get_list(
        self,
        filters: dict | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[Deal]:
        stmt = select(Deal).order_by(Deal.created_at.desc())
        if filters:
            if filters.get("user_id") is not None:
                stmt = stmt.where(Deal.user_id == filters["user_id"])
            if filters.get("status"):
                stmt = stmt.where(Deal.status == filters["status"])
            if filters.get("product"):
                stmt = stmt.where(Deal.product == filters["product"])
            if filters.get("manager_id") is not None:
                stmt = stmt.where(Deal.assigned_manager_id == filters["manager_id"])
        result = await self._session.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().all())
