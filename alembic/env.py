"""Alembic env — async-aware, reads DB URL from app settings."""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from app.core.config import settings
from app.models.base import Base

# Import every table module so Base.metadata is populated.
# The canonical User and RefreshToken live under app.models.users.*, not
# app.models.tables.user / refresh_token (those exist as unused duplicates
# that collide on __tablename__ if imported alongside the canonical
# versions).
import app.models.users.entities  # noqa: F401   (User)
import app.models.users.refresh_token  # noqa: F401   (RefreshToken)
import app.models.users.referral  # noqa: F401   (ReferralAccrual)
import app.models.users.bonus  # noqa: F401   (BonusWithdrawalRequest)
import app.models.tables.chat  # noqa: F401
import app.models.tables.message  # noqa: F401
import app.models.tables.file  # noqa: F401
import app.models.tables.support_agent  # noqa: F401
import app.models.settings  # noqa: F401   (PlatformSettings)
import app.models.audit_log  # noqa: F401   (AuditLog)
import app.models.sms_notification  # noqa: F401   (SMSNotification)


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
