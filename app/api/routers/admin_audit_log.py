"""Админ-панель, раздел Audit Log: журнал действий с фильтрами и CSV-экспортом."""
from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.manager_auth import get_current_admin
from app.api.deps.subject_auth import SubjectRow
from app.core.database import get_async_session
from app.models.audit_log import AuditLog
from app.models.dto.admin import AuditLogEntryResponse

router = APIRouter(prefix="/admin/audit-log", tags=["admin"])


def _filtered_query(
    performed_by: int | None,
    performed_by_type: str | None,
    action: str | None,
    target_type: str | None,
    start_date: date | None,
    end_date: date | None,
):
    stmt = select(AuditLog)
    if performed_by is not None:
        stmt = stmt.where(AuditLog.performed_by_id == performed_by)
    if performed_by_type is not None:
        stmt = stmt.where(AuditLog.performed_by_type == performed_by_type)
    if action is not None:
        if action not in AuditLog.ACTIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"action must be one of {AuditLog.ACTIONS}",
            )
        stmt = stmt.where(AuditLog.action == action)
    if target_type is not None:
        if target_type not in AuditLog.TARGET_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"target_type must be one of {AuditLog.TARGET_TYPES}",
            )
        stmt = stmt.where(AuditLog.target_type == target_type)
    if start_date is not None:
        stmt = stmt.where(AuditLog.created_at >= datetime.combine(start_date, time.min))
    if end_date is not None:
        stmt = stmt.where(AuditLog.created_at <= datetime.combine(end_date, time.max))
    return stmt


@router.get("/", response_model=list[AuditLogEntryResponse])
async def list_audit_log(
    performed_by: int | None = Query(default=None),
    performed_by_type: str | None = Query(default=None),
    action: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_async_session),
    _admin: SubjectRow = Depends(get_current_admin),
) -> list[AuditLogEntryResponse]:
    stmt = _filtered_query(
        performed_by, performed_by_type, action, target_type, start_date, end_date
    )
    result = await session.execute(
        stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset(skip)
        .limit(limit)
    )
    return [AuditLogEntryResponse.model_validate(e) for e in result.scalars().all()]


@router.get("/export/", response_class=StreamingResponse)
async def export_audit_log_csv(
    performed_by: int | None = Query(default=None),
    performed_by_type: str | None = Query(default=None),
    action: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    session: AsyncSession = Depends(get_async_session),
    _admin: SubjectRow = Depends(get_current_admin),
) -> StreamingResponse:
    stmt = _filtered_query(
        performed_by, performed_by_type, action, target_type, start_date, end_date
    )
    result = await session.execute(stmt.order_by(AuditLog.created_at, AuditLog.id))
    logs = list(result.scalars().all())

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "id", "performed_by_type", "performed_by_id", "action",
            "target_type", "target_id", "old_value", "new_value",
            "comment", "created_at",
        ],
    )
    writer.writeheader()
    for entry in logs:
        writer.writerow(
            {
                "id": entry.id,
                "performed_by_type": entry.performed_by_type,
                "performed_by_id": entry.performed_by_id or "",
                "action": entry.action,
                "target_type": entry.target_type,
                "target_id": entry.target_id,
                "old_value": json.dumps(entry.old_value, ensure_ascii=False)
                if entry.old_value
                else "",
                "new_value": json.dumps(entry.new_value, ensure_ascii=False)
                if entry.new_value
                else "",
                "comment": entry.comment or "",
                "created_at": entry.created_at.isoformat(),
            }
        )

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_log.csv"},
    )
