"""Юнит-тесты ролевых зависимостей: get_current_manager / get_current_admin /
require_owner_admin. Работают на in-memory SubjectRow без БД."""

import pytest
from fastapi import HTTPException

from app.api.deps.manager_auth import (
    get_current_admin,
    get_current_manager,
    require_owner_admin,
)
from app.api.deps.subject_auth import Subject, SubjectRow
from app.models.tables.support_agent import SupportAgent


def _subject_row(role: str, permissions: list[str] | None = None, is_owner: bool = False) -> SubjectRow:
    agent = SupportAgent(
        login="x",
        password_hash="h",
        display_name="X",
        role=role,
        permissions=permissions or [],
        is_owner=is_owner,
    )
    agent.id = 1
    return SubjectRow(subject=Subject(type="support", id=1), support=agent)


@pytest.mark.asyncio
async def test_manager_with_required_permissions_passes():
    dep = get_current_manager(["chats", "reports"])
    row = _subject_row("manager", permissions=["chats", "reports", "users_view"])
    assert await dep(subject=row) is row


@pytest.mark.asyncio
async def test_manager_missing_permission_rejected():
    dep = get_current_manager(["deals_create"])
    row = _subject_row("manager", permissions=["chats"])
    with pytest.raises(HTTPException) as ei:
        await dep(subject=row)
    assert ei.value.status_code == 403
    assert "deals_create" in ei.value.detail


@pytest.mark.asyncio
async def test_admin_bypasses_permission_check():
    dep = get_current_manager(["deals_create", "certificates"])
    row = _subject_row("admin", permissions=[])
    assert await dep(subject=row) is row


@pytest.mark.asyncio
async def test_no_permissions_required_accepts_any_manager():
    dep = get_current_manager()
    row = _subject_row("manager", permissions=[])
    assert await dep(subject=row) is row


@pytest.mark.asyncio
async def test_get_current_admin_rejects_manager():
    with pytest.raises(HTTPException) as ei:
        await get_current_admin(subject=_subject_row("manager"))
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_get_current_admin_accepts_admin():
    row = _subject_row("admin")
    assert await get_current_admin(subject=row) is row


@pytest.mark.asyncio
async def test_require_owner_admin_rejects_plain_admin():
    with pytest.raises(HTTPException) as ei:
        await require_owner_admin(subject=_subject_row("admin", is_owner=False))
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_require_owner_admin_accepts_owner():
    row = _subject_row("admin", is_owner=True)
    assert await require_owner_admin(subject=row) is row
