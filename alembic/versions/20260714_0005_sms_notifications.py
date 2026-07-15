"""sms_notifications: очередь SMS-уведомлений

Revision ID: 20260714_0005
Revises: 20260714_0004
Create Date: 2026-07-14
"""

import sqlalchemy as sa
from alembic import op


revision = "20260714_0005"
down_revision = "20260714_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sms_notifications",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("template", sa.String(64), nullable=False),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_sms_notifications_user_id", "sms_notifications", ["user_id"]
    )
    op.create_index("ix_sms_notifications_status", "sms_notifications", ["status"])
    op.create_index("ix_sms_notifications_sent_at", "sms_notifications", ["sent_at"])


def downgrade() -> None:
    op.drop_index("ix_sms_notifications_sent_at", table_name="sms_notifications")
    op.drop_index("ix_sms_notifications_status", table_name="sms_notifications")
    op.drop_index("ix_sms_notifications_user_id", table_name="sms_notifications")
    op.drop_table("sms_notifications")
