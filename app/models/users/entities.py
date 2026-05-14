from decimal import Decimal

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Numeric, ForeignKey, Integer

from app.models.base import Base, int_pk, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int_pk]
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    patronymic: Mapped[str | None] = mapped_column(String(100), nullable=True)

    balance: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    pending_balance: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
    )
    referral_code: Mapped[str] = mapped_column(
        String(16), unique=True, nullable=False, index=True
    )
    referrer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
