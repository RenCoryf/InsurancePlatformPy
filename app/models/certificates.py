import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

CERTIFICATE_STATUSES = (
    "new",
    "confirming",
    "in_progress",
    "completed",
    "cancelled",
)


class CertificateRequest(Base):
    """Заявка на обмен бонусов на сертификат партнёра.

    При создании бонусы НЕ списываются — только при завершении
    (``completed``, менеджер прикрепляет файл сертификата). Отмена
    выполненной заявки бонусы не возвращает. Общение идёт в bonus-чате
    пользователя (один на пользователя).
    """

    __tablename__ = "certificate_requests"

    STATUS_NEW = "new"
    STATUS_CONFIRMING = "confirming"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUSES = CERTIFICATE_STATUSES

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    partner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("partners.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    bonus_chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chats.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=STATUS_NEW, server_default=STATUS_NEW, index=True
    )
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_manager_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("support_agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    certificate_file_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class CertificateStatusEvent(Base):
    """История смен статуса заявки на сертификат."""

    __tablename__ = "certificate_status_events"

    BY_USER = "user"
    BY_MANAGER = "manager"
    BY_SYSTEM = "system"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    certificate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("certificate_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    old_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    new_status: Mapped[str] = mapped_column(String(24), nullable=False)
    changed_by_type: Mapped[str] = mapped_column(String(16), nullable=False)
    changed_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
