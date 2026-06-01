from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, int_pk


class BonusWithdrawalRequest(Base):
    """Заявка пользователя на вывод бонусов.

    Создаётся при запросе на вывод. Пока статус ``pending`` — ожидает
    одобрения менеджера (отдельный сервис, реализуется позже). После
    ``approve`` сумма списывается с ``users.balance`` и заявка
    переводится в ``approved``. ``rejected`` зарезервирован под будущее.
    """

    __tablename__ = "bonus_withdrawal_requests"

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"

    id: Mapped[int_pk]
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=STATUS_PENDING, index=True
    )
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
