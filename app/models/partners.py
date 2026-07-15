from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, int_pk


class Partner(Base):
    """Партнёр программы обмена бонусов на сертификаты.

    ``min_exchange``/``max_exchange``/``exchange_step`` — лимиты суммы
    обмена; ``logo_file_key`` — ключ логотипа в MinIO.
    """

    __tablename__ = "partners"

    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"
    STATUSES = (STATUS_ACTIVE, STATUS_INACTIVE)

    id: Mapped[int_pk]
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    logo_file_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    min_exchange: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    max_exchange: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    exchange_step: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("100"), server_default="100"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=STATUS_ACTIVE, server_default=STATUS_ACTIVE, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
