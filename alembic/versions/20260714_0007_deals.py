"""deals: сделки, история статусов, привязка начислений к сделке

Revision ID: 20260714_0007
Revises: 20260714_0006
Create Date: 2026-07-14
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision = "20260714_0007"
down_revision = "20260714_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "application_id",
            UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product", sa.String(16), nullable=False),
        sa.Column("policy_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("policy_date", sa.Date(), nullable=False),
        sa.Column("accrual_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="new"),
        sa.Column(
            "assigned_manager_id",
            sa.Integer(),
            sa.ForeignKey("support_agents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_deals_application_id", "deals", ["application_id"])
    op.create_index("ix_deals_user_id", "deals", ["user_id"])
    op.create_index("ix_deals_product", "deals", ["product"])
    op.create_index("ix_deals_status", "deals", ["status"])
    op.create_index("ix_deals_assigned_manager_id", "deals", ["assigned_manager_id"])

    op.create_table(
        "deal_status_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "deal_id",
            UUID(as_uuid=True),
            sa.ForeignKey("deals.id", ondelete="CASCADE"),
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
        "ix_deal_status_events_deal_id", "deal_status_events", ["deal_id"]
    )

    op.add_column(
        "referral_accruals",
        sa.Column(
            "deal_id",
            UUID(as_uuid=True),
            sa.ForeignKey("deals.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_referral_accruals_deal_id", "referral_accruals", ["deal_id"])


def downgrade() -> None:
    op.drop_index("ix_referral_accruals_deal_id", table_name="referral_accruals")
    op.drop_column("referral_accruals", "deal_id")
    op.drop_index("ix_deal_status_events_deal_id", table_name="deal_status_events")
    op.drop_table("deal_status_events")
    op.drop_index("ix_deals_assigned_manager_id", table_name="deals")
    op.drop_index("ix_deals_status", table_name="deals")
    op.drop_index("ix_deals_product", table_name="deals")
    op.drop_index("ix_deals_user_id", table_name="deals")
    op.drop_index("ix_deals_application_id", table_name="deals")
    op.drop_table("deals")
