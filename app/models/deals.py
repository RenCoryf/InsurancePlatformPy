import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.applications import APPLICATION_STATUSES


class Deal(Base):
    """Сделка (оформление полиса).

    Создаётся менеджером, опционально привязана к заявке. При переходе в
    статус ``policy_issued`` по реферальной сети источника начисляются
    бонусы (в ``pending_balance``, доступны с ``accrual_date``); при отмене
    выпущенного полиса pending-начисления отменяются.
    """

    __tablename__ = "deals"

    STATUS_NEW = "new"
    STATUS_POLICY_ISSUED = "policy_issued"
    STATUS_REJECTED = "rejected"
    STATUS_ERROR = "error"
    STATUSES = APPLICATION_STATUSES

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    policy_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    policy_date: Mapped[date] = mapped_column(Date, nullable=False)
    # policy_date + settings.bonus_accrual_delay_days
    accrual_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=STATUS_NEW, server_default=STATUS_NEW, index=True
    )
    assigned_manager_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("support_agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class DealStatusEvent(Base):
    """История смен статуса сделки."""

    __tablename__ = "deal_status_events"

    BY_MANAGER = "manager"
    BY_SYSTEM = "system"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    deal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("deals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    old_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    new_status: Mapped[str] = mapped_column(String(24), nullable=False)
    changed_by_type: Mapped[str] = mapped_column(String(16), nullable=False)
    changed_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
