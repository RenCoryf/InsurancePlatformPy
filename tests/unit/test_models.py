"""Smoke tests that the new ORM models import and have the expected columns."""

from sqlalchemy import inspect


def test_support_agent_columns():
    from app.models.tables.support_agent import SupportAgent

    cols = {c.name for c in inspect(SupportAgent).columns}
    assert cols == {
        "id", "login", "password_hash", "display_name", "is_active",
        "created_at", "updated_at",
    }
    assert SupportAgent.__tablename__ == "support_agents"
