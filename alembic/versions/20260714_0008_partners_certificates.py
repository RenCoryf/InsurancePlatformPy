"""partners + certificate_requests: обмен бонусов на сертификаты

Revision ID: 20260714_0008
Revises: 20260714_0007
Create Date: 2026-07-14
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision = "20260714_0008"
down_revision = "20260714_0007"
branch_labels = None
depends_on = None

SEED_PARTNERS = (
    "Магнит",
    "Магнит Косметик",
    "Пятёрочка",
    "Ozon",
    "Wildberries",
)


def upgrade() -> None:
    partners = op.create_table(
        "partners",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("logo_file_key", sa.String(255), nullable=True),
        sa.Column("min_exchange", sa.Numeric(14, 2), nullable=False),
        sa.Column("max_exchange", sa.Numeric(14, 2), nullable=True),
        sa.Column(
            "exchange_step", sa.Numeric(14, 2), nullable=False, server_default="100"
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_partners_status", "partners", ["status"])

    op.bulk_insert(
        partners,
        [
            {"name": name, "min_exchange": 100, "exchange_step": 100, "status": "active"}
            for name in SEED_PARTNERS
        ],
    )

    op.create_table(
        "certificate_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "partner_id",
            sa.Integer(),
            sa.ForeignKey("partners.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "bonus_chat_id",
            UUID(as_uuid=True),
            sa.ForeignKey("chats.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="new"),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column(
            "assigned_manager_id",
            sa.Integer(),
            sa.ForeignKey("support_agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("certificate_file_key", sa.String(255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_certificate_requests_user_id", "certificate_requests", ["user_id"])
    op.create_index("ix_certificate_requests_partner_id", "certificate_requests", ["partner_id"])
    op.create_index("ix_certificate_requests_status", "certificate_requests", ["status"])
    op.create_index(
        "ix_certificate_requests_assigned_manager_id",
        "certificate_requests",
        ["assigned_manager_id"],
    )

    op.create_table(
        "certificate_status_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "certificate_id",
            UUID(as_uuid=True),
            sa.ForeignKey("certificate_requests.id", ondelete="CASCADE"),
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
        "ix_certificate_status_events_certificate_id",
        "certificate_status_events",
        ["certificate_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_certificate_status_events_certificate_id",
        table_name="certificate_status_events",
    )
    op.drop_table("certificate_status_events")
    op.drop_index(
        "ix_certificate_requests_assigned_manager_id", table_name="certificate_requests"
    )
    op.drop_index("ix_certificate_requests_status", table_name="certificate_requests")
    op.drop_index("ix_certificate_requests_partner_id", table_name="certificate_requests")
    op.drop_index("ix_certificate_requests_user_id", table_name="certificate_requests")
    op.drop_table("certificate_requests")
    op.drop_index("ix_partners_status", table_name="partners")
    op.drop_table("partners")
