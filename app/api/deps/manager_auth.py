"""Ролевые зависимости для менеджеров и администраторов (JWT support-агентов).

Роль и права проверяются по строке ``support_agents`` из БД на каждый запрос
(get_current_support уже загружает её), а не по клеймам токена — отзыв прав
действует немедленно.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status

from app.api.deps.subject_auth import SubjectRow
from app.api.deps.support_auth import get_current_support
from app.models.tables.support_agent import SupportAgent


def get_current_manager(permissions_required: list[str] | None = None):
    """Фабрика зависимости: support-агент с каждым из требуемых прав.

    Администратор проходит любую проверку прав. Использование:
    ``Depends(get_current_manager(["chats"]))``.
    """
    required = list(permissions_required or [])

    async def _dep(subject: SubjectRow = Depends(get_current_support)) -> SubjectRow:
        agent = subject.support
        missing = [p for p in required if not agent.has_permission(p)]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"missing permissions: {', '.join(missing)}",
            )
        return subject

    return _dep


async def get_current_admin(
    subject: SubjectRow = Depends(get_current_support),
) -> SubjectRow:
    if subject.support.role != SupportAgent.ROLE_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="admin role required"
        )
    return subject


async def require_owner_admin(
    subject: SubjectRow = Depends(get_current_admin),
) -> SubjectRow:
    if not subject.support.is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="owner admin required"
        )
    return subject
