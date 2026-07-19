import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Chat(Base):
    __tablename__ = "chats"

    TYPE_MAIN = "main"
    TYPE_BONUS = "bonus"
    TYPE_INSURANCE = "insurance"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # main/bonus — по одному на пользователя; insurance-чатов много (по заявке на каждый).
        Index(
            "uq_chats_owner_type",
            "owner_user_id", "type",
            unique=True,
            postgresql_where=text("type IN ('main', 'bonus')"),
        ),
        CheckConstraint("type IN ('main', 'bonus', 'insurance')", name="ck_chats_type"),
        Index("ix_chats_last_message_at", "last_message_at", postgresql_using="btree"),
    )
