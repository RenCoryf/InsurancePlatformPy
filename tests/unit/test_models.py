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


def test_chat_columns():
    from app.models.tables.chat import Chat

    cols = {c.name for c in inspect(Chat).columns}
    assert cols == {
        "id", "owner_user_id", "type", "created_at", "last_message_at",
    }
    assert Chat.__tablename__ == "chats"
    constraints = {c.name for c in Chat.__table__.constraints if c.name}
    assert "uq_chats_owner_type" in constraints


def test_file_columns():
    from app.models.tables.file import File

    cols = {c.name for c in inspect(File).columns}
    assert cols == {
        "id", "chat_id", "uploader_subject_type", "uploader_subject_id",
        "original_name", "mime_type", "size_bytes", "minio_key", "created_at",
    }
    assert File.__tablename__ == "files"
