"""Журналирование критичных действий в таблицу ``audit_log``.

Запись добавляется в текущую транзакцию (flush, без commit) — она
фиксируется атомарно вместе с самим действием при commit вызывающего кода.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


class AuditService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def log(
        self,
        *,
        performed_by_type: str,
        action: str,
        target_type: str,
        target_id: int | str,
        performed_by_id: int | None = None,
        old_value: dict[str, Any] | None = None,
        new_value: dict[str, Any] | None = None,
        comment: str | None = None,
    ) -> AuditLog:
        if performed_by_type not in AuditLog.PERFORMED_BY_TYPES:
            raise ValueError(f"unknown performed_by_type: {performed_by_type!r}")
        if action not in AuditLog.ACTIONS:
            raise ValueError(f"unknown audit action: {action!r}")
        if target_type not in AuditLog.TARGET_TYPES:
            raise ValueError(f"unknown target_type: {target_type!r}")

        entry = AuditLog(
            performed_by_type=performed_by_type,
            performed_by_id=performed_by_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            old_value=old_value,
            new_value=new_value,
            comment=comment,
        )
        self._session.add(entry)
        await self._session.flush()
        return entry
