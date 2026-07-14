"""settings.sms_templates: переопределения SMS-шаблонов

Revision ID: 20260714_0009
Revises: 20260714_0008
Create Date: 2026-07-14
"""

import sqlalchemy as sa
from alembic import op


revision = "20260714_0009"
down_revision = "20260714_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("sms_templates", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("settings", "sms_templates")
