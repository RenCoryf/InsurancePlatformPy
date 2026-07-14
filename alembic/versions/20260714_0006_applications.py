"""applications: заявки, история статусов, insurance-чаты, system-сообщения

Revision ID: 20260714_0006
Revises: 20260714_0005
Create Date: 2026-07-14
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision = "20260714_0006"
down_revision = "20260714_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Чаты: разрешаем тип insurance (их у пользователя много — по одному на
    # заявку), поэтому UNIQUE(owner_user_id, type) сужается до main/bonus.
    op.drop_constraint("uq_chats_owner_type", "chats", type_="unique")
    op.execute(
        "CREATE UNIQUE INDEX uq_chats_owner_type ON chats (owner_user_id, type) "
        "WHERE type IN ('main', 'bonus')"
    )
    op.drop_constraint("ck_chats_type", "chats", type_="check")
    op.create_check_constraint(
        "ck_chats_type", "chats", "type IN ('main', 'bonus', 'insurance')"
    )

    # Сообщения: системный отправитель (sender_subject_id = 0).
    op.drop_constraint("ck_messages_sender_subject_type", "messages", type_="check")
    op.create_check_constraint(
        "ck_messages_sender_subject_type",
        "messages",
        "sender_subject_type IN ('user', 'support', 'system')",
    )

    op.create_table(
        "applications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "chat_id",
            UUID(as_uuid=True),
            sa.ForeignKey("chats.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("product", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="new"),
        sa.Column(
            "assigned_manager_id",
            sa.Integer(),
            sa.ForeignKey("support_agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("manager_comment", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_applications_user_id", "applications", ["user_id"])
    op.create_index("ix_applications_product", "applications", ["product"])
    op.create_index("ix_applications_status", "applications", ["status"])
    op.create_index(
        "ix_applications_assigned_manager_id", "applications", ["assigned_manager_id"]
    )

    op.create_table(
        "application_status_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "application_id",
            UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("old_status", sa.String(24), nullable=True),
        sa.Column("new_status", sa.String(24), nullable=False),
        sa.Column("changed_by_type", sa.String(16), nullable=False),
        sa.Column("changed_by_id", sa.Integer(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_application_status_events_application_id",
        "application_status_events",
        ["application_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_application_status_events_application_id",
        table_name="application_status_events",
    )
    op.drop_table("application_status_events")
    op.drop_index("ix_applications_assigned_manager_id", table_name="applications")
    op.drop_index("ix_applications_status", table_name="applications")
    op.drop_index("ix_applications_product", table_name="applications")
    op.drop_index("ix_applications_user_id", table_name="applications")
    op.drop_table("applications")

    op.drop_constraint("ck_messages_sender_subject_type", "messages", type_="check")
    op.create_check_constraint(
        "ck_messages_sender_subject_type",
        "messages",
        "sender_subject_type IN ('user', 'support')",
    )

    op.execute("DELETE FROM chats WHERE type = 'insurance'")
    op.drop_constraint("ck_chats_type", "chats", type_="check")
    op.create_check_constraint("ck_chats_type", "chats", "type IN ('main', 'bonus')")
    op.drop_index("uq_chats_owner_type", table_name="chats")
    op.create_unique_constraint(
        "uq_chats_owner_type", "chats", ["owner_user_id", "type"]
    )
