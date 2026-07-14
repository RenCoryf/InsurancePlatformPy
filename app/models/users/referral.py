import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, int_pk


class ReferralAccrual(Base):
    """Реферальное начисление.

    Создаётся при доходном событии исходного пользователя (`source_user_id`)
    в пользу его аплайна (`user_id`) на конкретном уровне.
    Пока статус ``pending`` — сумма лежит в ``users.pending_balance``.
    После наступления ``available_at`` сервис переносит сумму в ``users.balance``
    и переключает статус на ``credited``. Отмена сделки-источника переводит
    pending-начисление в ``cancelled`` и возвращает pending_balance.
    """

    __tablename__ = "referral_accruals"

    STATUS_PENDING = "pending"
    STATUS_CREDITED = "credited"
    STATUS_CANCELLED = "cancelled"

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Сделка-источник начисления; NULL для ручных/тестовых начислений.
    deal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("deals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    percent: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    base_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=STATUS_PENDING, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    available_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    credited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
