"""Smoke tests that the new ORM models import and have the expected columns."""

from sqlalchemy import inspect


def test_support_agent_columns():
    from app.models.tables.support_agent import SupportAgent

    cols = {c.name for c in inspect(SupportAgent).columns}
    assert cols == {
        "id", "login", "password_hash", "display_name", "is_active",
        "created_at", "updated_at",
        "role", "permissions", "invited_by_admin_id", "invite_token",
        "invite_expires_at", "phone", "is_owner",
    }
    assert SupportAgent.__tablename__ == "support_agents"


def test_user_status_columns():
    from app.models.users.entities import User

    cols = {c.name for c in inspect(User).columns}
    assert {"status", "blocked_reason", "blocked_comment", "blocked_at", "blocked_by_admin_id"} <= cols


def test_settings_and_audit_log_models():
    from app.models.audit_log import AuditLog
    from app.models.settings import PlatformSettings

    settings_cols = {c.name for c in inspect(PlatformSettings).columns}
    assert {
        "bonus_level_1_percent", "bonus_level_2_percent", "bonus_level_3_percent",
        "bonus_level_4_percent", "bonus_accrual_delay_days", "bonus_min_exchange",
        "blocked_user_level_rule", "sms_provider", "sms_sender_id",
        "sms_daily_limit_per_user", "root_referral_code", "root_referral_active",
    } <= settings_cols
    assert PlatformSettings.__tablename__ == "settings"

    audit_cols = {c.name for c in inspect(AuditLog).columns}
    assert audit_cols == {
        "id", "performed_by_type", "performed_by_id", "action", "target_type",
        "target_id", "old_value", "new_value", "comment", "created_at",
    }
    assert AuditLog.__tablename__ == "audit_log"


def test_chat_columns():
    from app.models.tables.chat import Chat

    cols = {c.name for c in inspect(Chat).columns}
    assert cols == {
        "id", "owner_user_id", "type", "created_at", "last_message_at",
    }
    assert Chat.__tablename__ == "chats"
    # main/bonus уникальны на пользователя через частичный индекс
    # (insurance-чатов много — по одному на заявку).
    indexes = {i.name: i for i in Chat.__table__.indexes}
    assert "uq_chats_owner_type" in indexes
    assert indexes["uq_chats_owner_type"].unique


def test_file_columns():
    from app.models.tables.file import File

    cols = {c.name for c in inspect(File).columns}
    assert cols == {
        "id", "chat_id", "uploader_subject_type", "uploader_subject_id",
        "original_name", "mime_type", "size_bytes", "minio_key", "created_at",
    }
    assert File.__tablename__ == "files"


def test_message_columns():
    from app.models.tables.message import Message

    cols = {c.name for c in inspect(Message).columns}
    assert cols == {
        "id", "chat_id", "sender_subject_type", "sender_subject_id",
        "kind", "body", "file_id", "client_msg_id", "created_at",
    }
    assert Message.__tablename__ == "messages"
