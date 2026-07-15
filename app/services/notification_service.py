"""Постановка SMS-уведомлений в очередь (таблица ``sms_notifications``).

Сервис только кладёт уведомление в очередь (flush, без commit — запись
фиксируется вместе с транзакцией вызывающего кода). Реальную отправку
делает фоновая задача :mod:`app.tasks.sms_job`.

Тексты шаблонов можно переопределить в настройках платформы
(``settings.sms_templates``, раздел Settings админки); дефолты ниже.
"""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sms_notification import SMSNotification
from app.models.users.entities import User

logger = logging.getLogger(__name__)

DEFAULT_SMS_TEMPLATES: dict[str, str] = {
    "registration_welcome": "Добро пожаловать! Ваш реферальный код: {referral_code}",
    "login_code": "Ваш код подтверждения: {code}. Действителен 10 минут.",
    "registration_code": "Код для регистрации: {code}. Действителен 10 минут.",
    "chat_new_message": "У вас новое сообщение от {sender}",
    "application_status_changed": "Статус заявки #{app_id}: {status}",
    "bonus_accrued": "Начислено {amount} бонусов",
    "bonus_manual_credit": "Начислено {amount} бонусов: {reason}",
    "certificate_confirming": "Ваша заявка на сертификат {partner} на рассмотрении",
    "certificate_completed": "Сертификат {partner} на {amount} бонусов готов! Файл — в бонусном чате",
    "certificate_cancelled": "Заявка на сертификат {partner} отменена: {reason}",
    "manager_invite": "Вас приглашают в систему. Перейдите: {link} для установки пароля",
}


class NotificationService:
    def __init__(self, session: AsyncSession, redis=None):
        self._session = session
        self._redis = redis

    async def get_templates(self) -> dict[str, str]:
        """Дефолтные шаблоны, поверх — переопределения из настроек платформы."""
        # Импорт здесь: SettingsService импортировать наверху нельзя из-за
        # соблазна обратной зависимости settings_service -> notification_service.
        from app.services.settings_service import SettingsService

        overrides: dict = {}
        try:
            platform = await SettingsService(self._session, self._redis).get_values()
            overrides = platform.get("sms_templates") or {}
        except Exception:
            logger.warning("Failed to load sms_templates from settings", exc_info=True)
        return {**DEFAULT_SMS_TEMPLATES, **overrides}

    @staticmethod
    def format_template(text: str, params: dict) -> str:
        """Подстановка параметров; при нехватке параметра — текст как есть."""
        try:
            return text.format(**params)
        except (KeyError, IndexError) as e:
            logger.error("Missing param %s for SMS template text %r", e, text)
            return text

    async def render_template(self, template: str, params: dict) -> str:
        templates = await self.get_templates()
        text = templates.get(template)
        if text is None:
            raise ValueError(f"unknown SMS template: {template!r}")
        return self.format_template(text, params)

    async def send(
        self, user_id: int, template: str, params: dict | None = None
    ) -> SMSNotification | None:
        """Поставить уведомление в очередь; None — если слать некому/некуда."""
        user = await self._session.get(User, user_id)
        if user is None or not user.phone:
            logger.warning("No phone for user %s, SMS %r skipped", user_id, template)
            return None

        params = params or {}
        text = await self.render_template(template, params)

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

    async def get_pending_count(self) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(SMSNotification)
            .where(SMSNotification.status == SMSNotification.STATUS_PENDING)
        )
        return int(result.scalar_one())
