"""user status fields, settings and audit_log tables

Revision ID: 20260713_0003
Revises: 20260602_0002
Create Date: 2026-07-13
"""

import sqlalchemy as sa
from alembic import op


revision = "20260713_0003"
down_revision = "20260602_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- users: статус + блокировка + анонимизация ---
    op.add_column(
        "users",
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
    )
    op.add_column("users", sa.Column("blocked_reason", sa.String(16), nullable=True))
    op.add_column("users", sa.Column("blocked_comment", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("blocked_at", sa.DateTime(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "blocked_by_admin_id",
            sa.Integer(),
            sa.ForeignKey("support_agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_users_status", "users", ["status"])

    # Анонимизация удалённого пользователя обнуляет phone/email.
    op.alter_column("users", "email", existing_type=sa.String(255), nullable=True)
    op.alter_column("users", "phone", existing_type=sa.String(20), nullable=True)

    # --- settings: единственная строка глобальных настроек ---
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("bonus_level_1_percent", sa.Numeric(5, 2), nullable=False, server_default="3.0"),
        sa.Column("bonus_level_2_percent", sa.Numeric(5, 2), nullable=False, server_default="3.0"),
        sa.Column("bonus_level_3_percent", sa.Numeric(5, 2), nullable=False, server_default="2.0"),
        sa.Column("bonus_level_4_percent", sa.Numeric(5, 2), nullable=False, server_default="1.0"),
        sa.Column("bonus_accrual_delay_days", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("bonus_min_exchange", sa.Numeric(14, 2), nullable=False, server_default="1000"),
        sa.Column("blocked_user_level_rule", sa.String(8), nullable=False, server_default="zero"),
        sa.Column("sms_provider", sa.String(32), nullable=False, server_default="smsc"),
        sa.Column("sms_sender_id", sa.String(32), nullable=False, server_default=""),
        sa.Column("sms_daily_limit_per_user", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("root_referral_code", sa.String(32), nullable=True),
        sa.Column("root_referral_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # --- audit_log ---
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("performed_by_type", sa.String(16), nullable=False),
        sa.Column("performed_by_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("target_type", sa.String(16), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("old_value", sa.JSON(), nullable=True),
        sa.Column("new_value", sa.JSON(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])
    op.create_index("ix_audit_log_target", "audit_log", ["target_type", "target_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_target", table_name="audit_log")
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_index("ix_audit_log_action", table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_table("settings")

    op.alter_column("users", "phone", existing_type=sa.String(20), nullable=False)
    op.alter_column("users", "email", existing_type=sa.String(255), nullable=False)

    op.drop_index("ix_users_status", table_name="users")
    op.drop_column("users", "blocked_by_admin_id")
    op.drop_column("users", "blocked_at")
    op.drop_column("users", "blocked_comment")
    op.drop_column("users", "blocked_reason")
    op.drop_column("users", "status")
