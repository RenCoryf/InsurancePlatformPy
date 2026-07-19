import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chat_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    sender_subject_type: Mapped[str] = mapped_column(String(20), nullable=False)
    sender_subject_id: Mapped[int] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("files.id", ondelete="RESTRICT"), nullable=True)
    client_msg_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        # system — служебные сообщения платформы (sender_subject_id = 0).
        CheckConstraint("sender_subject_type IN ('user', 'support', 'system')", name="ck_messages_sender_subject_type"),
        CheckConstraint("kind IN ('message', 'file')", name="ck_messages_kind"),
        CheckConstraint(
            "(kind = 'message' AND body IS NOT NULL AND file_id IS NULL) OR "
            "(kind = 'file'    AND file_id IS NOT NULL AND body IS NULL)",
            name="ck_messages_kind_body_xor",
        ),
        Index(
            "uq_messages_chat_client_msg_id",
            "chat_id", "client_msg_id",
            unique=True,
            postgresql_where=text("client_msg_id IS NOT NULL"),
        ),
        Index("ix_messages_chat_created", "chat_id", "created_at", "id", postgresql_ops={"created_at": "DESC", "id": "DESC"}),
    )
