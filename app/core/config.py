from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "insurance_platform"
    db_user: str = "postgres"
    db_password: str = "postgres"

    jwt_secret_key: str = "your-secret-key-change-in-production-min-32-chars"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30

    referral_accrual_delay_days: int = 15
    referral_link_base_url: str = "https://example.com/r/"

    # Chat / file / admin / MinIO config (added 2026-05-21)
    environment: str = "development"  # set to "production" to enable startup secret guards
    internal_secret: str = "dev-internal-secret-change-me"
    max_message_bytes: int = 64_000
    max_file_bytes: int = 20_000_000  # ТЗ п. 8.3: до 20 МБ на файл

    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "chat-files"
    minio_secure: bool = False

    admin_login: str = "admin"
    admin_password: str = "admin"

    # Фоновые задачи (APScheduler): начисление созревших бонусов, отправка SMS
    scheduler_enabled: bool = True

    # Redis (OTP-коды, кеш настроек, лимиты SMS)
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db: int = 0

    # SMSC.ru credentials (пустые значения = dev-режим, код пишется в лог)
    smsc_login: str = ""
    smsc_password: str = ""
    sms_lk_url: str = "https://smsc.ru"

    # Приглашение менеджера по SMS
    invite_link_base_url: str = "https://example.com"
    support_invite_ttl_hours: int = 72

    # Первичный владелец (scripts/init_owner.py)
    owner_login: str = "owner"
    owner_password: str = ""
    owner_phone: str | None = None

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


settings = Settings()
