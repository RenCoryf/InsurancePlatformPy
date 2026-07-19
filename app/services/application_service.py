"""Заявки на страховые продукты (Applications).

Создание заявки открывает чат типа ``insurance`` и кладёт в него системное
сообщение. Смена статуса пишется в ``application_status_events``, дублируется
системным сообщением в чат, ставит SMS в очередь и логируется в audit_log.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.applications import (
    APPLICATION_STATUSES,
    PRODUCTS,
    Application,
    ApplicationStatusEvent,
)
from app.models.audit_log import AuditLog
from app.models.tables.chat import Chat
from app.models.tables.message import Message
from app.models.tables.support_agent import SupportAgent
from app.models.users.entities import User
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService

PRODUCT_TITLES = {
    "osago": "ОСАГО",
    "kasko": "КАСКО",
    "property": "Страхование имущества",
    "personal": "Личное страхование",
    "pds": "ПДС",
    "legal": "Юридическая защита",
}

# Служебный sender_subject_id для sender_subject_type='system'.
SYSTEM_SENDER_ID = 0


def validate_product(product: str) -> None:
    if product not in PRODUCTS:
        raise ValueError(f"unknown product: {product!r}")


def validate_status(status: str) -> None:
    if status not in APPLICATION_STATUSES:
        raise ValueError(f"unknown status: {status!r}")


class ApplicationService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def _add_system_message(self, chat: Chat, text: str) -> Message:
        message = Message(
            chat_id=chat.id,
            sender_subject_type="system",
            sender_subject_id=SYSTEM_SENDER_ID,
            kind="message",
            body=text,
        )
        self._session.add(message)
        chat.last_message_at = datetime.utcnow()
        await self._session.flush()
        return message

    async def _create_chat(self, user_id: int) -> Chat:
        chat = Chat(owner_user_id=user_id, type=Chat.TYPE_INSURANCE)
        self._session.add(chat)
        await self._session.flush()
        return chat

    async def create_from_user(self, user_id: int, product: str) -> Application:
        """Создать заявку от пользователя + открыть insurance-чат."""
        validate_product(product)

        app = Application(
            user_id=user_id,
            product=product,
            status=Application.STATUS_NEW,
            created_by=Application.CREATED_BY_USER,
        )
        self._session.add(app)
        await self._session.flush()

        chat = await self._create_chat(user_id)
        app.chat_id = chat.id
        await self._add_system_message(
            chat, f"Заявка на {PRODUCT_TITLES[product]} создана"
        )

        await self._session.commit()
        await self._session.refresh(app)
        return app

    async def create_from_manager(
        self,
        manager_id: int,
        user_id: int,
        product: str,
        comment: str | None = None,
    ) -> Application:
        """Создать заявку от имени пользователя (менеджером)."""
        validate_product(product)
        if await self._session.get(User, user_id) is None:
            raise ValueError("user not found")

        app = Application(
            user_id=user_id,
            product=product,
            status=Application.STATUS_NEW,
            created_by=Application.CREATED_BY_MANAGER,
            assigned_manager_id=manager_id,
            manager_comment=comment,
        )
        self._session.add(app)
        await self._session.flush()

        chat = await self._create_chat(user_id)
        app.chat_id = chat.id

        manager = await self._session.get(SupportAgent, manager_id)
        manager_name = manager.display_name if manager is not None else "менеджер"
        await self._add_system_message(
            chat,
            f"Заявка на {PRODUCT_TITLES[product]} создана менеджером {manager_name}",
        )

        await AuditService(self._session).log(
            performed_by_type=AuditLog.BY_MANAGER,
            performed_by_id=manager_id,
            action=AuditLog.ACTION_APPLICATION_CREATE,
            target_type=AuditLog.TARGET_APPLICATION,
            target_id=str(app.id),
            new_value={"user_id": user_id, "product": product},
            comment=comment,
        )

        await self._session.commit()
        await self._session.refresh(app)
        return app

    async def change_status(
        self,
        application_id: UUID,
        new_status: str,
        manager_id: int,
        comment: str | None = None,
    ) -> Application:
        """Смена статуса заявки менеджером."""
        validate_status(new_status)

        app = await self._session.get(Application, application_id)
        if app is None:
            raise ValueError("application not found")

        old_status = app.status
        if new_status == old_status:
            raise ValueError("application is already in this status")

        app.status = new_status
        app.updated_at = datetime.utcnow()

        self._session.add(
            ApplicationStatusEvent(
                application_id=app.id,
                old_status=old_status,
                new_status=new_status,
                changed_by_type=ApplicationStatusEvent.BY_MANAGER,
                changed_by_id=manager_id,
                comment=comment,
            )
        )

        if app.chat_id is not None:
            chat = await self._session.get(Chat, app.chat_id)
            if chat is not None:
                await self._add_system_message(
                    chat, f"Статус изменён: {old_status} → {new_status}"
                )

        await NotificationService(self._session).send(
            app.user_id,
            "application_status_changed",
            {"app_id": str(app.id), "status": new_status},
        )

        await AuditService(self._session).log(
            performed_by_type=AuditLog.BY_MANAGER,
            performed_by_id=manager_id,
            action=AuditLog.ACTION_APPLICATION_STATUS_CHANGE,
            target_type=AuditLog.TARGET_APPLICATION,
            target_id=str(app.id),
            old_value={"status": old_status},
            new_value={"status": new_status},
            comment=comment,
        )

        await self._session.commit()
        await self._session.refresh(app)
        return app

    async def get(self, application_id: UUID) -> Application | None:
        return await self._session.get(Application, application_id)

    async def get_status_events(
        self, application_id: UUID
    ) -> list[ApplicationStatusEvent]:
        result = await self._session.execute(
            select(ApplicationStatusEvent)
            .where(ApplicationStatusEvent.application_id == application_id)
            .order_by(ApplicationStatusEvent.created_at, ApplicationStatusEvent.id)
        )
        return list(result.scalars().all())

    async def get_list(
        self,
        filters: dict | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[Application]:
        stmt = select(Application).order_by(Application.created_at.desc())
        if filters:
            if filters.get("user_id") is not None:
                stmt = stmt.where(Application.user_id == filters["user_id"])
            if filters.get("status"):
                stmt = stmt.where(Application.status == filters["status"])
            if filters.get("product"):
                stmt = stmt.where(Application.product == filters["product"])
            if filters.get("manager_id") is not None:
                stmt = stmt.where(
                    Application.assigned_manager_id == filters["manager_id"]
                )
        result = await self._session.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().all())
