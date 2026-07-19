"""Фоновая задача отправки SMS-уведомлений из очереди ``sms_notifications``.

Запускается APScheduler'ом раз в минуту (см. ``app.main.lifespan``). Берёт
до 100 pending-уведомлений, соблюдая дневной лимит на пользователя
(``settings.sms_daily_limit_per_user``): при достижении лимита уведомление
остаётся в очереди до следующего окна. Без SMSC-креденшалов работает
dev-режим — текст пишется в лог, уведомление помечается отправленным.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.sms_notification import SMSNotification
from app.services.settings_service import SettingsService
from app.services.sms_service import SMSService_SMSC

logger = logging.getLogger(__name__)

BATCH_SIZE = 100


def _build_sms_service(sender: str | None) -> SMSService_SMSC | None:
    """SMSC-клиент из env-креденшалов; None — dev-режим (только лог)."""
    if settings.smsc_login and settings.smsc_password:
        return SMSService_SMSC.with_credentials(
            username=settings.smsc_login,
            password=settings.smsc_password,
            lk_url=settings.sms_lk_url,
            sender=sender,
        )
    return None


async def _sent_last_day_by_user(
    session: AsyncSession, user_ids: set[int], since: datetime
) -> dict[int, int]:
    if not user_ids:
        return {}
    result = await session.execute(
        select(SMSNotification.user_id, func.count())
        .where(
            SMSNotification.user_id.in_(user_ids),
            SMSNotification.status == SMSNotification.STATUS_SENT,
            SMSNotification.sent_at >= since,
        )
        .group_by(SMSNotification.user_id)
    )
    return {user_id: count for user_id, count in result.all()}


async def _send_batch(
    session: AsyncSession, sms_service: SMSService_SMSC | None
) -> dict[str, int]:
    result = await session.execute(
        select(SMSNotification)
        .where(SMSNotification.status == SMSNotification.STATUS_PENDING)
        .order_by(SMSNotification.id)
        .limit(BATCH_SIZE)
    )
    pending = list(result.scalars().all())
    stats = {"sent": 0, "failed": 0, "deferred": 0}
    if not pending:
        return stats

    platform = await SettingsService(session).get_values()
    daily_limit = int(platform["sms_daily_limit_per_user"])
    if sms_service is None:
        sms_service = _build_sms_service(platform.get("sms_sender_id") or None)

    now = datetime.utcnow()
    sent_today = await _sent_last_day_by_user(
        session, {n.user_id for n in pending}, since=now - timedelta(days=1)
    )

    for notification in pending:
        if sent_today.get(notification.user_id, 0) >= daily_limit:
            logger.warning(
                "SMS daily limit reached for user %d, notification %d deferred",
                notification.user_id,
                notification.id,
            )
            stats["deferred"] += 1
            continue

        try:
            if sms_service is not None:
                await sms_service.send_message(notification.phone, notification.text)
            else:
                logger.info(
                    "SMSC is not configured; SMS to %s: %s",
                    notification.phone,
                    notification.text,
                )
            notification.status = SMSNotification.STATUS_SENT
            notification.sent_at = datetime.utcnow()
            sent_today[notification.user_id] = (
                sent_today.get(notification.user_id, 0) + 1
            )
            stats["sent"] += 1
        except Exception:
            logger.exception("Failed to send SMS notification %d", notification.id)
            notification.status = SMSNotification.STATUS_FAILED
            stats["failed"] += 1

    await session.commit()
    return stats


async def send_pending_sms_job(
    session: AsyncSession | None = None,
    sms_service: SMSService_SMSC | None = None,
) -> dict[str, int]:
    """Точка входа планировщика; ошибки не пробрасываются в scheduler."""
    try:
        if session is not None:
            stats = await _send_batch(session, sms_service)
        else:
            # Импорт здесь, чтобы модуль не тянул подключение к БД при импорте в тестах.
            from app.core.database import AsyncSessionLocal

            async with AsyncSessionLocal() as own_session:
                stats = await _send_batch(own_session, sms_service)
        if any(stats.values()):
            logger.info(
                "SMS job: %d sent, %d failed, %d deferred",
                stats["sent"],
                stats["failed"],
                stats["deferred"],
            )
        return stats
    except Exception:
        logger.exception("SMS job failed")
        return {"sent": 0, "failed": 0, "deferred": 0}
