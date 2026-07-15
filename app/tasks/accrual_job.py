"""Фоновая задача процессинга созревших реферальных начислений.

Запускается APScheduler'ом раз в час (см. ``app.main.lifespan``): переводит
все начисления с ``available_at <= now`` из ``pending_balance`` в ``balance``,
ставит получателям SMS ``bonus_accrued`` и пишет системную запись в аудит.
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.services.audit_service import AuditService
from app.services.referral_service import ReferralService

logger = logging.getLogger(__name__)


async def _process(session: AsyncSession) -> int:
    matured = await ReferralService(session).process_matured_accruals()
    count = len(matured)
    if count:
        await AuditService(session).log(
            performed_by_type=AuditLog.BY_SYSTEM,
            action=AuditLog.ACTION_BONUS_ACCRUAL_AUTO,
            target_type=AuditLog.TARGET_BONUS,
            target_id="auto",
            comment=f"Auto-processed {count} accruals",
        )
        await session.commit()
    return count


async def process_matured_accruals_job(session: AsyncSession | None = None) -> int:
    """Точка входа планировщика; ошибки не пробрасываются в scheduler."""
    try:
        if session is not None:
            count = await _process(session)
        else:
            # Импорт здесь, чтобы модуль не тянул подключение к БД при импорте в тестах.
            from app.core.database import AsyncSessionLocal

            async with AsyncSessionLocal() as own_session:
                count = await _process(own_session)
        logger.info("Processed %d matured accruals", count)
        return count
    except Exception:
        logger.exception("Accrual job failed")
        return 0
