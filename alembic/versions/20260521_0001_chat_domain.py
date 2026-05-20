"""chat domain

Revision ID: 20260521_0001
Revises: 20260521_0000
Create Date: 2026-05-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision = "20260521_0001"
down_revision = "20260521_0000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "support_agents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("login", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_support_agents_login", "support_agents", ["login"], unique=True)

    op.create_table(
        "chats",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("owner_user_id", "type", name="uq_chats_owner_type"),
        sa.CheckConstraint("type IN ('main', 'bonus')", name="ck_chats_type"),
    )
    op.create_index("ix_chats_owner_user_id", "chats", ["owner_user_id"])
    op.create_index("ix_chats_last_message_at", "chats", ["last_message_at"])

    op.create_table(
        "files",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("chat_id", UUID(as_uuid=True), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploader_subject_type", sa.String(20), nullable=False),
        sa.Column("uploader_subject_id", sa.Integer(), nullable=False),
        sa.Column("original_name", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("minio_key", sa.String(512), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("uploader_subject_type IN ('user', 'support')", name="ck_files_uploader_subject_type"),
    )
    op.create_index("ix_files_chat_id", "files", ["chat_id"])

    op.create_table(
        "messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("chat_id", UUID(as_uuid=True), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_subject_type", sa.String(20), nullable=False),
        sa.Column("sender_subject_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("file_id", UUID(as_uuid=True), sa.ForeignKey("files.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("client_msg_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("sender_subject_type IN ('user', 'support')", name="ck_messages_sender_subject_type"),
        sa.CheckConstraint("kind IN ('message', 'file')", name="ck_messages_kind"),
        sa.CheckConstraint(
            "(kind = 'message' AND body IS NOT NULL AND file_id IS NULL) OR "
            "(kind = 'file'    AND file_id IS NOT NULL AND body IS NULL)",
            name="ck_messages_kind_body_xor",
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_messages_chat_client_msg_id ON messages (chat_id, client_msg_id) "
        "WHERE client_msg_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_messages_chat_created ON messages (chat_id, created_at DESC, id DESC)"
    )


def downgrade() -> None:
    op.drop_index("ix_messages_chat_created", table_name="messages")
    op.drop_index("uq_messages_chat_client_msg_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_files_chat_id", table_name="files")
    op.drop_table("files")
    op.drop_index("ix_chats_last_message_at", table_name="chats")
    op.drop_index("ix_chats_owner_user_id", table_name="chats")
    op.drop_table("chats")
    op.drop_index("ix_support_agents_login", table_name="support_agents")
    op.drop_table("support_agents")
