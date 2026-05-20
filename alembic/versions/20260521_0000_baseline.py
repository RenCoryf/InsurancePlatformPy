"""baseline — existing users and refresh_tokens tables

Revision ID: 20260521_0000
Revises:
Create Date: 2026-05-21
"""

import sqlalchemy as sa
from alembic import op


revision = "20260521_0000"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=True),
        sa.Column("last_name", sa.String(100), nullable=True),
        sa.Column("patronymic", sa.String(100), nullable=True),
        sa.Column("balance", sa.Numeric(14, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("pending_balance", sa.Numeric(14, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("referral_code", sa.String(16), nullable=False, unique=True),
        sa.Column("referrer_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_users_referral_code", "users", ["referral_code"], unique=True)
    op.create_index("ix_users_referrer_id", "users", ["referrer_id"])

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("token", sa.String(500), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_refresh_tokens_token", "refresh_tokens", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_token", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index("ix_users_referrer_id", table_name="users")
    op.drop_index("ix_users_referral_code", table_name="users")
    op.drop_table("users")
