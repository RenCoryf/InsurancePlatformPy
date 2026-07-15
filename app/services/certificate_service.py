"""Заявки на обмен бонусов на сертификаты партнёров.

Создание заявки бонусы не списывает — только резервирует намерение и
открывает (или переиспользует) bonus-чат пользователя. Списание происходит
при завершении заявки менеджером (``complete``, с файлом сертификата в
MinIO). Отмена бонусы не возвращает. Каждая смена статуса пишется в
``certificate_status_events``, дублируется системным сообщением в чат и
логируется в audit_log; завершение и отмена ставят SMS в очередь.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import BinaryIO
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.audit_log import AuditLog
from app.models.certificates import CertificateRequest, CertificateStatusEvent
from app.models.partners import Partner
from app.models.tables.chat import Chat
from app.models.tables.message import Message
from app.models.users.entities import User
from app.services.application_service import SYSTEM_SENDER_ID
from app.services.audit_service import AuditService
from app.services.bonus_service import BonusService
from app.services.notification_service import NotificationService


def validate_certificate_status(status: str) -> None:
    if status not in CertificateRequest.STATUSES:
        raise ValueError(f"unknown status: {status!r}")


class CertificateService:
    def __init__(self, session: AsyncSession, minio_client=None):
        self._session = session
        self._minio = minio_client

    @staticmethod
    def _quantize(amount: Decimal) -> Decimal:
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

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

    async def _add_system_message_to_chat_id(self, chat_id: UUID, text: str) -> None:
        chat = await self._session.get(Chat, chat_id)
        if chat is not None:
            await self._add_system_message(chat, text)

    async def _get_or_create_bonus_chat(self, user_id: int) -> Chat:
        """Bonus-чат один на пользователя (частичный UNIQUE в chats)."""
        result = await self._session.execute(
            select(Chat).where(
                Chat.owner_user_id == user_id, Chat.type == Chat.TYPE_BONUS
            )
        )
        chat = result.scalar_one_or_none()
        if chat is None:
            chat = Chat(owner_user_id=user_id, type=Chat.TYPE_BONUS)
            self._session.add(chat)
            await self._session.flush()
        return chat

    async def create(
        self, user_id: int, partner_id: int, amount: Decimal
    ) -> CertificateRequest:
        """Подать заявку на сертификат (бонусы не списываются)."""
        if amount <= 0:
            raise ValueError("amount must be positive")
        amount = self._quantize(amount)

        user = await self._session.get(User, user_id)
        if user is None:
            raise ValueError("user not found")
        if (user.balance or Decimal("0")) < amount:
            raise ValueError("insufficient balance")

        partner = await self._session.get(Partner, partner_id)
        if partner is None:
            raise ValueError("partner not found")
        if partner.status != Partner.STATUS_ACTIVE:
            raise ValueError("partner is not active")
        if amount < partner.min_exchange:
            raise ValueError(f"amount is below partner minimum {partner.min_exchange}")
        if partner.max_exchange is not None and amount > partner.max_exchange:
            raise ValueError(f"amount is above partner maximum {partner.max_exchange}")

        chat = await self._get_or_create_bonus_chat(user_id)

        cert = CertificateRequest(
            user_id=user_id,
            partner_id=partner_id,
            bonus_chat_id=chat.id,
            amount=amount,
            status=CertificateRequest.STATUS_NEW,
        )
        self._session.add(cert)
        await self._session.flush()

        await self._add_system_message(
            chat, f"Заявка на сертификат {partner.name} на сумму {amount} бонусов"
        )

        await AuditService(self._session).log(
            performed_by_type=AuditLog.BY_USER,
            performed_by_id=user_id,
            action=AuditLog.ACTION_CERTIFICATE_REQUEST_CREATE,
            target_type=AuditLog.TARGET_CERTIFICATE,
            target_id=str(cert.id),
            new_value={"partner": partner.name, "amount": str(amount)},
        )

        await self._session.commit()
        await self._session.refresh(cert)
        return cert

    async def change_status(
        self,
        certificate_id: UUID,
        new_status: str,
        manager_id: int,
        comment: str | None = None,
    ) -> CertificateRequest:
        """Смена статуса менеджером (new → confirming → in_progress).

        ``completed``/``cancelled`` идут через :meth:`complete`/:meth:`cancel` —
        там списание бонусов, файл и SMS.
        """
        validate_certificate_status(new_status)
        if new_status in (
            CertificateRequest.STATUS_COMPLETED,
            CertificateRequest.STATUS_CANCELLED,
        ):
            raise ValueError("use complete/cancel endpoints for this status")

        cert = await self._session.get(CertificateRequest, certificate_id)
        if cert is None:
            raise ValueError("certificate not found")
        old_status = cert.status
        if new_status == old_status:
            raise ValueError("certificate is already in this status")
        if old_status in (
            CertificateRequest.STATUS_COMPLETED,
            CertificateRequest.STATUS_CANCELLED,
        ):
            raise ValueError("certificate is already finalized")

        cert.status = new_status
        cert.assigned_manager_id = manager_id
        cert.updated_at = datetime.utcnow()

        self._session.add(
            CertificateStatusEvent(
                certificate_id=cert.id,
                old_status=old_status,
                new_status=new_status,
                changed_by_type=CertificateStatusEvent.BY_MANAGER,
                changed_by_id=manager_id,
                comment=comment,
            )
        )

        await self._add_system_message_to_chat_id(
            cert.bonus_chat_id, f"Статус изменён: {old_status} → {new_status}"
        )

        if new_status == CertificateRequest.STATUS_CONFIRMING:
            partner = await self._session.get(Partner, cert.partner_id)
            await NotificationService(self._session).send(
                cert.user_id,
                "certificate_confirming",
                {"partner": partner.name if partner else ""},
            )

        await AuditService(self._session).log(
            performed_by_type=AuditLog.BY_MANAGER,
            performed_by_id=manager_id,
            action=AuditLog.ACTION_CERTIFICATE_STATUS_CHANGE,
            target_type=AuditLog.TARGET_CERTIFICATE,
            target_id=str(cert.id),
            old_value={"status": old_status},
            new_value={"status": new_status},
            comment=comment,
        )

        await self._session.commit()
        await self._session.refresh(cert)
        return cert

    async def complete(
        self,
        certificate_id: UUID,
        manager_id: int,
        *,
        stream: BinaryIO,
        size_bytes: int,
        content_type: str,
    ) -> CertificateRequest:
        """Завершить заявку: файл сертификата в MinIO + списание бонусов."""
        if self._minio is None:
            raise ValueError("file storage is not available")

        cert = await self._session.get(CertificateRequest, certificate_id)
        if cert is None:
            raise ValueError("certificate not found")
        old_status = cert.status
        if old_status in (
            CertificateRequest.STATUS_COMPLETED,
            CertificateRequest.STATUS_CANCELLED,
        ):
            raise ValueError("certificate is already finalized")

        # Списание до загрузки файла: при нехватке бонусов файл не заливаем.
        await BonusService(self._session).debit(
            user_id=cert.user_id,
            amount=cert.amount,
            reason=f"Обмен на сертификат {cert.id}",
            performed_by=manager_id,
            commit=False,
        )

        file_key = f"certificates/{cert.user_id}/{uuid.uuid4()}"
        await asyncio.to_thread(
            self._minio.put_object,
            settings.minio_bucket,
            file_key,
            stream,
            size_bytes,
            content_type=content_type,
        )

        cert.certificate_file_key = file_key
        cert.status = CertificateRequest.STATUS_COMPLETED
        cert.assigned_manager_id = manager_id
        cert.updated_at = datetime.utcnow()

        self._session.add(
            CertificateStatusEvent(
                certificate_id=cert.id,
                old_status=old_status,
                new_status=CertificateRequest.STATUS_COMPLETED,
                changed_by_type=CertificateStatusEvent.BY_MANAGER,
                changed_by_id=manager_id,
            )
        )

        await self._add_system_message_to_chat_id(
            cert.bonus_chat_id, "Сертификат выдан! Он приложен к этому сообщению."
        )

        partner = await self._session.get(Partner, cert.partner_id)
        await NotificationService(self._session).send(
            cert.user_id,
            "certificate_completed",
            {
                "partner": partner.name if partner else "",
                "amount": str(cert.amount),
            },
        )

        await AuditService(self._session).log(
            performed_by_type=AuditLog.BY_MANAGER,
            performed_by_id=manager_id,
            action=AuditLog.ACTION_CERTIFICATE_COMPLETE,
            target_type=AuditLog.TARGET_CERTIFICATE,
            target_id=str(cert.id),
            old_value={"status": old_status},
            new_value={"status": CertificateRequest.STATUS_COMPLETED},
        )

        await self._session.commit()
        await self._session.refresh(cert)
        return cert

    async def cancel(
        self, certificate_id: UUID, manager_id: int, reason: str
    ) -> CertificateRequest:
        """Отменить заявку. Списанные при завершении бонусы не возвращаются."""
        cert = await self._session.get(CertificateRequest, certificate_id)
        if cert is None:
            raise ValueError("certificate not found")
        old_status = cert.status
        if old_status == CertificateRequest.STATUS_CANCELLED:
            raise ValueError("certificate is already cancelled")

        cert.status = CertificateRequest.STATUS_CANCELLED
        cert.cancel_reason = reason
        cert.assigned_manager_id = manager_id
        cert.updated_at = datetime.utcnow()

        self._session.add(
            CertificateStatusEvent(
                certificate_id=cert.id,
                old_status=old_status,
                new_status=CertificateRequest.STATUS_CANCELLED,
                changed_by_type=CertificateStatusEvent.BY_MANAGER,
                changed_by_id=manager_id,
                comment=reason,
            )
        )

        await self._add_system_message_to_chat_id(
            cert.bonus_chat_id, f"Заявка отменена: {reason}"
        )

        partner = await self._session.get(Partner, cert.partner_id)
        await NotificationService(self._session).send(
            cert.user_id,
            "certificate_cancelled",
            {"partner": partner.name if partner else "", "reason": reason},
        )

        await AuditService(self._session).log(
            performed_by_type=AuditLog.BY_MANAGER,
            performed_by_id=manager_id,
            action=AuditLog.ACTION_CERTIFICATE_CANCEL,
            target_type=AuditLog.TARGET_CERTIFICATE,
            target_id=str(cert.id),
            old_value={"status": old_status},
            new_value={"status": CertificateRequest.STATUS_CANCELLED, "reason": reason},
        )

        await self._session.commit()
        await self._session.refresh(cert)
        return cert

    async def get_download_url(self, certificate_id: UUID) -> str:
        cert = await self._session.get(CertificateRequest, certificate_id)
        if cert is None:
            raise ValueError("certificate not found")
        if not cert.certificate_file_key:
            raise ValueError("certificate file not found")
        if self._minio is None:
            raise ValueError("file storage is not available")
        return await asyncio.to_thread(
            self._minio.presigned_get_object,
            settings.minio_bucket,
            cert.certificate_file_key,
        )

    async def get(self, certificate_id: UUID) -> CertificateRequest | None:
        return await self._session.get(CertificateRequest, certificate_id)

    async def get_status_events(
        self, certificate_id: UUID
    ) -> list[CertificateStatusEvent]:
        result = await self._session.execute(
            select(CertificateStatusEvent)
            .where(CertificateStatusEvent.certificate_id == certificate_id)
            .order_by(CertificateStatusEvent.created_at, CertificateStatusEvent.id)
        )
        return list(result.scalars().all())

    async def get_list(
        self,
        filters: dict | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[CertificateRequest]:
        stmt = select(CertificateRequest).order_by(CertificateRequest.created_at.desc())
        if filters:
            if filters.get("user_id") is not None:
                stmt = stmt.where(CertificateRequest.user_id == filters["user_id"])
            if filters.get("status"):
                stmt = stmt.where(CertificateRequest.status == filters["status"])
            if filters.get("partner_id") is not None:
                stmt = stmt.where(CertificateRequest.partner_id == filters["partner_id"])
        result = await self._session.execute(stmt.offset(skip).limit(limit))
        return list(result.scalars().all())
