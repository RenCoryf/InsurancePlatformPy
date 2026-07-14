"""Постановка SMS-уведомлений в очередь (таблица ``sms_notifications``).

Сервис только кладёт уведомление в очередь (flush, без commit — запись
фиксируется вместе с транзакцией вызывающего кода). Реальную отправку
делает фоновая задача :mod:`app.tasks.sms_job`.
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sms_notification import SMSNotification
from app.models.users.entities import User

logger = logging.getLogger(__name__)

SMS_TEMPLATES: dict[str, str] = {
    "registration_welcome": "Добро пожаловать! Ваш реферальный код: {referral_code}",
    "bonus_accrued": "Начислено {amount} бонусов",
    "application_status_changed": "Статус заявки #{app_id}: {status}",
    "certificate_completed": "Сертификат {partner} на {amount} бонусов готов! Файл — в бонусном чате",
    "certificate_cancelled": "Заявка на сертификат {partner} отменена: {reason}",
    "bonus_manual_credit": "Начислено {amount} бонусов: {reason}",
}


class NotificationService:
    def __init__(self, session: AsyncSession):
        self._session = session

    @staticmethod
    def render_template(template: str, params: dict) -> str:
        text = SMS_TEMPLATES.get(template)
        if text is None:
            raise ValueError(f"unknown SMS template: {template!r}")
        return text.format(**params)

    async def send(
        self, user_id: int, template: str, params: dict | None = None
    ) -> SMSNotification | None:
        """Поставить уведомление в очередь; None — если слать некому/некуда."""
        user = await self._session.get(User, user_id)
        if user is None or not user.phone:
            return None

        params = params or {}
        text = self.render_template(template, params)

        notification = SMSNotification(
            user_id=user_id,
            phone=user.phone,
            template=template,
            params=params,
            text=text,
            status=SMSNotification.STATUS_PENDING,
        )
        self._session.add(notification)
        await self._session.flush()
        return notification
