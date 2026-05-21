import base64

import pytest
from fastapi import HTTPException

from app.api.deps.admin_auth import admin_basic_auth


def _basic(login: str, password: str) -> str:
    raw = f"{login}:{password}".encode()
    return "Basic " + base64.b64encode(raw).decode()


@pytest.mark.asyncio
async def test_accepts_correct_credentials(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_login", "admin")
    monkeypatch.setattr(settings, "admin_password", "s3cret")

    await admin_basic_auth(authorization=_basic("admin", "s3cret"))


@pytest.mark.asyncio
async def test_rejects_wrong_password(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_login", "admin")
    monkeypatch.setattr(settings, "admin_password", "s3cret")

    with pytest.raises(HTTPException) as ei:
        await admin_basic_auth(authorization=_basic("admin", "wrong"))
    assert ei.value.status_code == 401


@pytest.mark.asyncio
async def test_rejects_missing_header(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_login", "admin")
    monkeypatch.setattr(settings, "admin_password", "s3cret")

    with pytest.raises(HTTPException) as ei:
        await admin_basic_auth(authorization="")
    assert ei.value.status_code == 401


@pytest.mark.asyncio
async def test_rejects_non_basic_scheme(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_login", "admin")
    monkeypatch.setattr(settings, "admin_password", "s3cret")

    with pytest.raises(HTTPException) as ei:
        await admin_basic_auth(authorization="Bearer foo")
    assert ei.value.status_code == 401
