"""support_agents: roles, permissions, SMS invites, owner flag

Revision ID: 20260714_0004
Revises: 20260713_0003
Create Date: 2026-07-14
"""

import sqlalchemy as sa
from alembic import op


revision = "20260714_0004"
down_revision = "20260713_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "support_agents",
        sa.Column("role", sa.String(16), nullable=False, server_default="manager"),
    )
    op.add_column(
        "support_agents",
        sa.Column("permissions", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "support_agents",
        sa.Column(
            "invited_by_admin_id",
            sa.Integer(),
            sa.ForeignKey("support_agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "support_agents", sa.Column("invite_token", sa.String(64), nullable=True)
    )
    op.add_column(
        "support_agents",
        sa.Column("invite_expires_at", sa.DateTime(), nullable=True),
    )
    op.add_column("support_agents", sa.Column("phone", sa.String(20), nullable=True))
    op.add_column(
        "support_agents",
        sa.Column("is_owner", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_unique_constraint(
        "uq_support_agents_invite_token", "support_agents", ["invite_token"]
    )
    op.create_unique_constraint("uq_support_agents_phone", "support_agents", ["phone"])


def downgrade() -> None:
    op.drop_constraint("uq_support_agents_phone", "support_agents", type_="unique")
    op.drop_constraint(
        "uq_support_agents_invite_token", "support_agents", type_="unique"
    )
    op.drop_column("support_agents", "is_owner")
    op.drop_column("support_agents", "phone")
    op.drop_column("support_agents", "invite_expires_at")
    op.drop_column("support_agents", "invite_token")
    op.drop_column("support_agents", "invited_by_admin_id")
    op.drop_column("support_agents", "permissions")
    op.drop_column("support_agents", "role")
