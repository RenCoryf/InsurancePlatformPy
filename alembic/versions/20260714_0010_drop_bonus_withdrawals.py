"""drop bonus_withdrawal_requests: ТЗ запрещает денежный вывод, только сертификаты

Revision ID: 20260714_0010
Revises: 20260714_0009
Create Date: 2026-07-14
"""

import sqlalchemy as sa
from alembic import op


revision = "20260714_0010"
down_revision = "20260714_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_bonus_withdrawal_requests_status", table_name="bonus_withdrawal_requests")
    op.drop_index("ix_bonus_withdrawal_requests_user_id", table_name="bonus_withdrawal_requests")
    op.drop_table("bonus_withdrawal_requests")


def downgrade() -> None:
    op.create_table(
        "bonus_withdrawal_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("comment", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_bonus_withdrawal_requests_user_id", "bonus_withdrawal_requests", ["user_id"])
    op.create_index("ix_bonus_withdrawal_requests_status", "bonus_withdrawal_requests", ["status"])
