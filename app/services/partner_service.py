"""Партнёры программы обмена бонусов (CRUD для админки + список для пользователей).

Логотип хранится в MinIO (ключ ``partners/logos/<uuid>``); клиент MinIO
опционален — без него операции с логотипом недоступны.
"""
from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.audit_log import AuditLog
from app.models.partners import Partner
from app.services.audit_service import AuditService


class PartnerService:
    def __init__(self, session: AsyncSession, minio_client=None):
        self._session = session
        self._minio = minio_client

    async def _upload_logo(
        self, stream: BinaryIO, size_bytes: int, content_type: str
    ) -> str:
        if self._minio is None:
            raise ValueError("file storage is not available")
        key = f"partners/logos/{uuid.uuid4()}"
        await asyncio.to_thread(
            self._minio.put_object,
            settings.minio_bucket,
            key,
            stream,
            size_bytes,
            content_type=content_type,
        )
        return key

    async def get_active_list(self) -> list[Partner]:
        result = await self._session.execute(
            select(Partner)
            .where(Partner.status == Partner.STATUS_ACTIVE)
            .order_by(Partner.name)
        )
        return list(result.scalars().all())

    async def get(self, partner_id: int) -> Partner | None:
        return await self._session.get(Partner, partner_id)

    async def get_all(self, skip: int = 0, limit: int = 50) -> list[Partner]:
        result = await self._session.execute(
            select(Partner).order_by(Partner.id).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def create(
        self,
        *,
        name: str,
        min_exchange: Decimal,
        admin_id: int,
        max_exchange: Decimal | None = None,
        exchange_step: Decimal = Decimal("100"),
        logo: tuple[BinaryIO, int, str] | None = None,
    ) -> Partner:
        if min_exchange <= 0:
            raise ValueError("min_exchange must be positive")
        if max_exchange is not None and max_exchange < min_exchange:
            raise ValueError("max_exchange must be >= min_exchange")
        if exchange_step <= 0:
            raise ValueError("exchange_step must be positive")

        logo_key = None
        if logo is not None:
            logo_key = await self._upload_logo(*logo)

        partner = Partner(
            name=name,
            min_exchange=min_exchange,
            max_exchange=max_exchange,
            exchange_step=exchange_step,
            logo_file_key=logo_key,
        )
        self._session.add(partner)
        await self._session.flush()

        await AuditService(self._session).log(
            performed_by_type=AuditLog.BY_ADMIN,
            performed_by_id=admin_id,
            action=AuditLog.ACTION_PARTNER_CREATE,
            target_type=AuditLog.TARGET_PARTNER,
            target_id=str(partner.id),
            new_value={"name": name, "min": str(min_exchange)},
        )

        await self._session.commit()
        await self._session.refresh(partner)
        return partner

    async def update(
        self,
        partner_id: int,
        *,
        admin_id: int,
        name: str | None = None,
        min_exchange: Decimal | None = None,
        max_exchange: Decimal | None = None,
        exchange_step: Decimal | None = None,
        status: str | None = None,
        logo: tuple[BinaryIO, int, str] | None = None,
    ) -> Partner:
        partner = await self._session.get(Partner, partner_id)
        if partner is None:
            raise ValueError("partner not found")
        if status is not None and status not in Partner.STATUSES:
            raise ValueError(f"status must be one of {Partner.STATUSES}")

        old_values = {
            "name": partner.name,
            "status": partner.status,
            "min": str(partner.min_exchange),
        }

        if name is not None:
            partner.name = name
        if min_exchange is not None:
            if min_exchange <= 0:
                raise ValueError("min_exchange must be positive")
            partner.min_exchange = min_exchange
        if max_exchange is not None:
            partner.max_exchange = max_exchange
        if exchange_step is not None:
            if exchange_step <= 0:
                raise ValueError("exchange_step must be positive")
            partner.exchange_step = exchange_step
        if status is not None:
            partner.status = status
        if logo is not None:
            partner.logo_file_key = await self._upload_logo(*logo)

        await AuditService(self._session).log(
            performed_by_type=AuditLog.BY_ADMIN,
            performed_by_id=admin_id,
            action=AuditLog.ACTION_PARTNER_UPDATE,
            target_type=AuditLog.TARGET_PARTNER,
            target_id=str(partner_id),
            old_value=old_values,
            new_value={
                "name": partner.name,
                "status": partner.status,
                "min": str(partner.min_exchange),
            },
        )

        await self._session.commit()
        await self._session.refresh(partner)
        return partner
