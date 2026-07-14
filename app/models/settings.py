from decimal import Decimal

from sqlalchemy import JSON, Boolean, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, int_pk


class PlatformSettings(Base, TimestampMixin):
    """Глобальные настройки платформы.

    Таблица из одной строки (id=1). Читается через
    :class:`app.services.settings_service.SettingsService` с кешем в Redis.
    Класс назван PlatformSettings, чтобы не путать с pydantic-настройками
    окружения ``app.core.config.Settings``.
    """

    __tablename__ = "settings"

    BLOCKED_RULE_SKIP = "skip"
    BLOCKED_RULE_ZERO = "zero"
    BLOCKED_RULES = (BLOCKED_RULE_SKIP, BLOCKED_RULE_ZERO)

    SINGLETON_ID = 1

    id: Mapped[int_pk]

    bonus_level_1_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("3.0"), server_default="3.0"
    )
    bonus_level_2_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("3.0"), server_default="3.0"
    )
    bonus_level_3_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("2.0"), server_default="2.0"
    )
    bonus_level_4_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("1.0"), server_default="1.0"
    )
    bonus_accrual_delay_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=15, server_default="15"
    )
    bonus_min_exchange: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("1000"), server_default="1000"
    )
    blocked_user_level_rule: Mapped[str] = mapped_column(
        String(8), nullable=False, default=BLOCKED_RULE_ZERO, server_default=BLOCKED_RULE_ZERO
    )

    sms_provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="smsc", server_default="smsc"
    )
    sms_sender_id: Mapped[str] = mapped_column(
        String(32), nullable=False, default="", server_default=""
    )
    sms_daily_limit_per_user: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default="5"
    )
    # Переопределения SMS-шаблонов ({имя: текст}); дефолты живут в
    # app.services.notification_service.DEFAULT_SMS_TEMPLATES.
    sms_templates: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )

    root_referral_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    root_referral_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
