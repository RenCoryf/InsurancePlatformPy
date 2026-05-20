import pytest


@pytest.mark.asyncio
async def test_internal_validation_returns_envelope(client):
    # Missing X-Internal-Secret → 403, but body shape is still well-defined.
    r = await client.post("/internal/auth/ws-validate", json={"token": "x", "chat_type": "main", "chat_id_hint": ""})
    assert r.status_code == 403
    assert "detail" in r.json()


@pytest.mark.asyncio
async def test_pydantic_validation_becomes_400_with_code_reason(client):
    from app.core.config import settings
    headers = {"X-Internal-Secret": settings.internal_secret}
    # Missing required field "token".
    r = await client.post("/internal/auth/ws-validate", json={"chat_type": "main", "chat_id_hint": ""}, headers=headers)
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["code"] == "validation"
    assert "reason" in body
