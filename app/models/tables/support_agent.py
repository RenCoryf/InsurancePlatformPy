from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, int_pk


class SupportAgent(Base, TimestampMixin):
    __tablename__ = "support_agents"

    ROLE_MANAGER = "manager"
    ROLE_ADMIN = "admin"
    ROLES = (ROLE_MANAGER, ROLE_ADMIN)

    PERMISSION_CHATS = "chats"
    PERMISSION_DEALS_CREATE = "deals_create"
    PERMISSION_CERTIFICATES = "certificates"
    PERMISSION_REPORTS = "reports"
    PERMISSION_USERS_VIEW = "users_view"
    ALLOWED_PERMISSIONS = (
        PERMISSION_CHATS,
        PERMISSION_DEALS_CREATE,
        PERMISSION_CERTIFICATES,
        PERMISSION_REPORTS,
        PERMISSION_USERS_VIEW,
    )

    id: Mapped[int_pk]
    login: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    role: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ROLE_MANAGER, server_default=ROLE_MANAGER
    )
    permissions: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    invited_by_admin_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("support_agents.id", ondelete="SET NULL"), nullable=True
    )
    invite_token: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True
    )
    # Наивный UTC — сравнивается с datetime.utcnow().
    invite_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    is_owner: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    def has_permission(self, permission: str) -> bool:
        if self.role == self.ROLE_ADMIN:
            return True
        return permission in (self.permissions or [])
