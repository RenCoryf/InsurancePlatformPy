"""referral_accruals and bonus_withdrawal_requests tables

Revision ID: 20260602_0002
Revises: 20260521_0001
Create Date: 2026-06-02
"""

import sqlalchemy as sa
from alembic import op


revision = "20260602_0002"
down_revision = "20260521_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "referral_accruals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("percent", sa.Numeric(5, 4), nullable=False),
        sa.Column("base_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("credited_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_referral_accruals_user_id", "referral_accruals", ["user_id"])
    op.create_index("ix_referral_accruals_source_user_id", "referral_accruals", ["source_user_id"])
    op.create_index("ix_referral_accruals_status", "referral_accruals", ["status"])
    op.create_index("ix_referral_accruals_available_at", "referral_accruals", ["available_at"])

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


def downgrade() -> None:
    op.drop_index("ix_bonus_withdrawal_requests_status", table_name="bonus_withdrawal_requests")
    op.drop_index("ix_bonus_withdrawal_requests_user_id", table_name="bonus_withdrawal_requests")
    op.drop_table("bonus_withdrawal_requests")

    op.drop_index("ix_referral_accruals_available_at", table_name="referral_accruals")
    op.drop_index("ix_referral_accruals_status", table_name="referral_accruals")
    op.drop_index("ix_referral_accruals_source_user_id", table_name="referral_accruals")
    op.drop_index("ix_referral_accruals_user_id", table_name="referral_accruals")
    op.drop_table("referral_accruals")
