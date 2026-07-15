import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

PRODUCTS = ("osago", "kasko", "property", "personal", "pds", "legal")

APPLICATION_STATUSES = (
    "new",
    "in_progress",
    "documents_needed",
    "calculation_ready",
    "paid",
    "policy_issued",
    "rejected",
    "error",
)


class Application(Base):
    """Заявка на страховой продукт.

    Создаётся пользователем (кнопка продукта) или менеджером от имени
    пользователя. При создании открывается чат типа ``insurance``
    (``chat_id`` проставляется после создания чата, поэтому nullable).
    """

    __tablename__ = "applications"

    STATUS_NEW = "new"
    STATUSES = APPLICATION_STATUSES

    CREATED_BY_USER = "user"
    CREATED_BY_MANAGER = "manager"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chat_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chats.id", ondelete="SET NULL"), nullable=True
    )
    product: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=STATUS_NEW, server_default=STATUS_NEW, index=True
    )
    assigned_manager_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("support_agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    manager_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class ApplicationStatusEvent(Base):
    """История смен статуса заявки."""

    __tablename__ = "application_status_events"

    BY_USER = "user"
    BY_MANAGER = "manager"
    BY_SYSTEM = "system"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
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
