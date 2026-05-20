import pytest
from jose import jwt

from app.core.config import settings
from app.models.users.entities import User


def _make_token(claims: dict) -> str:
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


@pytest.fixture
async def secret_headers():
    return {"X-Internal-Secret": settings.internal_secret}


@pytest.mark.asyncio
async def test_ws_validate_user_lazy_creates(client, db_session, secret_headers):
    u = User(email="a@b.c", phone="+1000000007", password_hash="x",
            first_name=None, last_name=None, patronymic=None,
            referral_code="REF007", referrer_id=None)
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)

    tok = _make_token({"sub": f"user:{u.id}", "role": "user"})
    r = await client.post("/internal/auth/ws-validate",
                          json={"token": tok, "chat_type": "main", "chat_id_hint": ""},
                          headers=secret_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == f"user:{u.id}"
    assert body["role"] == "user"
    assert body["chat_id"]


@pytest.mark.asyncio
async def test_ws_validate_missing_secret_403(client):
    r = await client.post("/internal/auth/ws-validate",
                          json={"token": "x", "chat_type": "main", "chat_id_hint": ""})
    assert r.status_code == 403
