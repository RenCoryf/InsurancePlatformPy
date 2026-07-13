from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    """Журнал критичных действий администраторов/менеджеров/системы."""

    __tablename__ = "audit_log"

    BY_ADMIN = "admin"
    BY_MANAGER = "manager"
    BY_SYSTEM = "system"
    PERFORMED_BY_TYPES = (BY_ADMIN, BY_MANAGER, BY_SYSTEM)

    ACTION_USER_BLOCK = "user_block"
    ACTION_USER_UNBLOCK = "user_unblock"
    ACTION_USER_DELETE = "user_delete"
    ACTION_BONUS_MANUAL_CREDIT = "bonus_manual_credit"
    ACTION_BONUS_MANUAL_DEBIT = "bonus_manual_debit"
    ACTION_BONUS_ACCRUAL_AUTO = "bonus_accrual_auto"
    ACTION_DEAL_AMOUNT_CHANGE = "deal_amount_change"
    ACTION_PERMISSION_CHANGE = "permission_change"
    ACTION_MANAGER_CREATE = "manager_create"
    ACTION_ADMIN_CREATE = "admin_create"
    ACTION_SETTINGS_UPDATE = "settings_update"
    ACTIONS = (
        ACTION_USER_BLOCK,
        ACTION_USER_UNBLOCK,
        ACTION_USER_DELETE,
        ACTION_BONUS_MANUAL_CREDIT,
        ACTION_BONUS_MANUAL_DEBIT,
        ACTION_BONUS_ACCRUAL_AUTO,
        ACTION_DEAL_AMOUNT_CHANGE,
        ACTION_PERMISSION_CHANGE,
        ACTION_MANAGER_CREATE,
        ACTION_ADMIN_CREATE,
        ACTION_SETTINGS_UPDATE,
    )

    TARGET_USER = "user"
    TARGET_DEAL = "deal"
    TARGET_BONUS = "bonus"
    TARGET_MANAGER = "manager"
    TARGET_ADMIN = "admin"
    TARGET_SETTINGS = "settings"
    TARGET_TYPES = (
        TARGET_USER,
        TARGET_DEAL,
        TARGET_BONUS,
        TARGET_MANAGER,
        TARGET_ADMIN,
        TARGET_SETTINGS,
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    performed_by_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # FK не ставим: system-события не ссылаются на support_agents,
    # а журнал должен переживать удаление учёток.
    performed_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
