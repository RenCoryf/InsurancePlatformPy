from app.core.config import settings


def test_chat_config_defaults():
    # These attributes must exist with sensible defaults.
    assert settings.max_message_bytes == 64_000
    assert settings.max_file_bytes == 20_000_000
    assert settings.minio_bucket == "chat-files"
    assert settings.minio_secure is False
    assert settings.environment == "development"


def test_chat_config_secrets_have_defaults_for_dev():
    # Defaults allow `pytest` to import without a .env file. Prod must override.
    assert settings.internal_secret == "dev-internal-secret-change-me"
    assert settings.admin_login == "admin"
    assert settings.admin_password == "admin"
    assert settings.minio_endpoint == "minio:9000"
    assert settings.minio_access_key == "minioadmin"
    assert settings.minio_secret_key == "minioadmin"
