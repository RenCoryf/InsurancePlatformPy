"""Админ-панель, разделы Managers и Admins.

Создание менеджера/администратора с SMS-инвайтом — POST /admin/managers/
в :mod:`app.api.routers.admin`. Здесь: списки, статистика, права и
блокировка. Раздел Admins доступен только владельцу (owner).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.manager_auth import get_current_admin, require_owner_admin
from app.api.deps.subject_auth import SubjectRow
from app.core.database import get_async_session
from app.models.applications import Application
from app.models.audit_log import AuditLog
from app.models.certificates import CertificateRequest
from app.models.deals import Deal
from app.models.dto.admin import (
    ManagerBlockRequest,
    ManagerStatsResponse,
    PermissionsUpdateRequest,
)
from app.models.dto.support_agent import SupportAgentResponse
from app.models.tables.support_agent import SupportAgent
from app.services.audit_service import AuditService

router = APIRouter(prefix="/admin", tags=["admin"])


def _agent_response(agent: SupportAgent) -> SupportAgentResponse:
    return SupportAgentResponse.model_validate(agent, from_attributes=True)


async def _get_agent_or_404(
    session: AsyncSession, agent_id: int, *, role: str
) -> SupportAgent:
    agent = await session.get(SupportAgent, agent_id)
    if agent is None or agent.role != role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return agent


# ---------------------------------------------------------------------------
# Managers
# ---------------------------------------------------------------------------


@router.get("/managers/", response_model=list[SupportAgentResponse])
async def list_managers(
    active_only: bool = Query(default=False),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_async_session),
    _admin: SubjectRow = Depends(get_current_admin),
) -> list[SupportAgentResponse]:
    stmt = (
        select(SupportAgent)
        .where(SupportAgent.role == SupportAgent.ROLE_MANAGER)
        .order_by(SupportAgent.id)
    )
    if active_only:
        stmt = stmt.where(SupportAgent.is_active == True)  # noqa: E712
    result = await session.execute(stmt.offset(skip).limit(limit))
    return [_agent_response(a) for a in result.scalars().all()]


@router.get("/managers/{manager_id}/stats/", response_model=ManagerStatsResponse)
async def manager_stats(
    manager_id: int,
    session: AsyncSession = Depends(get_async_session),
    _admin: SubjectRow = Depends(get_current_admin),
) -> ManagerStatsResponse:
    """Статистика менеджера: заявки, сделки, сертификаты в работе."""
    await _get_agent_or_404(session, manager_id, role=SupportAgent.ROLE_MANAGER)

    async def _count(model, column) -> int:
        result = await session.execute(
            select(func.count()).select_from(model).where(column == manager_id)
        )
        return int(result.scalar_one())

    return ManagerStatsResponse(
        manager_id=manager_id,
        applications_count=await _count(Application, Application.assigned_manager_id),
        deals_count=await _count(Deal, Deal.assigned_manager_id),
        certificates_count=await _count(
            CertificateRequest, CertificateRequest.assigned_manager_id
        ),
        average_response_time_seconds=None,
    )


@router.patch("/managers/{manager_id}/permissions/", response_model=SupportAgentResponse)
async def update_manager_permissions(
    manager_id: int,
    payload: PermissionsUpdateRequest,
    session: AsyncSession = Depends(get_async_session),
    admin: SubjectRow = Depends(get_current_admin),
) -> SupportAgentResponse:
    manager = await _get_agent_or_404(session, manager_id, role=SupportAgent.ROLE_MANAGER)

    old_permissions = list(manager.permissions or [])
    if payload.permissions != old_permissions:
        manager.permissions = payload.permissions
        await AuditService(session).log(
            performed_by_type=AuditLog.BY_ADMIN,
            performed_by_id=admin.support.id,
            action=AuditLog.ACTION_PERMISSION_CHANGE,
            target_type=AuditLog.TARGET_MANAGER,
            target_id=manager.id,
            old_value={"permissions": old_permissions},
            new_value={"permissions": payload.permissions},
        )
        await session.commit()
        await session.refresh(manager)
    return _agent_response(manager)


@router.patch("/managers/{manager_id}/block/", response_model=SupportAgentResponse)
async def block_manager(
    manager_id: int,
    payload: ManagerBlockRequest | None = None,
    session: AsyncSession = Depends(get_async_session),
    admin: SubjectRow = Depends(get_current_admin),
) -> SupportAgentResponse:
    """Заблокировать менеджера (is_active=False, вход невозможен)."""
    manager = await _get_agent_or_404(session, manager_id, role=SupportAgent.ROLE_MANAGER)
    if not manager.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="manager is already blocked"
        )

    manager.is_active = False
    await AuditService(session).log(
        performed_by_type=AuditLog.BY_ADMIN,
        performed_by_id=admin.support.id,
        action=AuditLog.ACTION_MANAGER_BLOCK,
        target_type=AuditLog.TARGET_MANAGER,
        target_id=manager.id,
        old_value={"is_active": True},
        new_value={"is_active": False},
        comment=payload.reason if payload else None,
    )
    await session.commit()
    await session.refresh(manager)
    return _agent_response(manager)


@router.patch("/managers/{manager_id}/unblock/", response_model=SupportAgentResponse)
async def unblock_manager(
    manager_id: int,
    session: AsyncSession = Depends(get_async_session),
    admin: SubjectRow = Depends(get_current_admin),
) -> SupportAgentResponse:
    manager = await _get_agent_or_404(session, manager_id, role=SupportAgent.ROLE_MANAGER)
    if manager.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="manager is not blocked"
        )

    manager.is_active = True
    await AuditService(session).log(
        performed_by_type=AuditLog.BY_ADMIN,
        performed_by_id=admin.support.id,
        action=AuditLog.ACTION_MANAGER_UNBLOCK,
        target_type=AuditLog.TARGET_MANAGER,
        target_id=manager.id,
        old_value={"is_active": False},
        new_value={"is_active": True},
    )
    await session.commit()
    await session.refresh(manager)
    return _agent_response(manager)


# ---------------------------------------------------------------------------
# Admins (только для owner)
# ---------------------------------------------------------------------------


@router.get("/admins/", response_model=list[SupportAgentResponse])
async def list_admins(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_async_session),
    _owner: SubjectRow = Depends(require_owner_admin),
) -> list[SupportAgentResponse]:
    result = await session.execute(
        select(SupportAgent)
        .where(SupportAgent.role == SupportAgent.ROLE_ADMIN)
        .order_by(SupportAgent.id)
        .offset(skip)
        .limit(limit)
    )
    return [_agent_response(a) for a in result.scalars().all()]


@router.patch("/admins/{admin_id}/permissions/", response_model=SupportAgentResponse)
async def update_admin_permissions(
    admin_id: int,
    payload: PermissionsUpdateRequest,
    session: AsyncSession = Depends(get_async_session),
    owner: SubjectRow = Depends(require_owner_admin),
) -> SupportAgentResponse:
    target = await _get_agent_or_404(session, admin_id, role=SupportAgent.ROLE_ADMIN)
    if target.is_owner:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="владельца нельзя редактировать",
        )

    old_permissions = list(target.permissions or [])
    if payload.permissions != old_permissions:
        target.permissions = payload.permissions
        await AuditService(session).log(
            performed_by_type=AuditLog.BY_ADMIN,
            performed_by_id=owner.support.id,
            action=AuditLog.ACTION_PERMISSION_CHANGE,
            target_type=AuditLog.TARGET_ADMIN,
            target_id=target.id,
            old_value={"permissions": old_permissions},
            new_value={"permissions": payload.permissions},
        )
        await session.commit()
        await session.refresh(target)
    return _agent_response(target)
