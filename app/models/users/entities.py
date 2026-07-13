from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Numeric, ForeignKey, Integer, DateTime, Text

from app.models.base import Base, int_pk, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    STATUS_ACTIVE = "active"
    STATUS_BLOCKED = "blocked"
    STATUS_DELETED = "deleted"
    STATUSES = (STATUS_ACTIVE, STATUS_BLOCKED, STATUS_DELETED)

    BLOCKED_REASONS = ("spam", "fraud", "duplicate", "request", "violation", "other")

    id: Mapped[int_pk]
    # email/phone nullable: анонимизация удалённого пользователя обнуляет их.
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
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

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=STATUS_ACTIVE,
        server_default=STATUS_ACTIVE,
        index=True,
    )
    blocked_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    blocked_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Наивный UTC, как в refresh_tokens.expires_at — сравнивается с datetime.utcnow().
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    blocked_by_admin_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("support_agents.id", ondelete="SET NULL"),
        nullable=True,
    )

    @property
    def is_active_status(self) -> bool:
        return self.status == self.STATUS_ACTIVE
