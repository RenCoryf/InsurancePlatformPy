import pytest
from fastapi import HTTPException

from app.api.deps.internal_secret import internal_secret_required


@pytest.mark.asyncio
async def test_accepts_matching_secret(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "internal_secret", "the-real-secret")

    # Should not raise.
    await internal_secret_required(x_internal_secret="the-real-secret")


@pytest.mark.asyncio
async def test_rejects_wrong_secret(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "internal_secret", "the-real-secret")

    with pytest.raises(HTTPException) as ei:
        await internal_secret_required(x_internal_secret="wrong")
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_rejects_missing_header(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "internal_secret", "the-real-secret")

    with pytest.raises(HTTPException) as ei:
        await internal_secret_required(x_internal_secret="")
    assert ei.value.status_code == 403
