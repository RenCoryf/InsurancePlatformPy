import pytest
from jose import jwt

from app.core.config import settings
from app.models.users.entities import User
from app.repositories.chat_repository import ChatRepository


def _make_token(uid: int) -> str:
    return jwt.encode({"sub": f"user:{uid}", "role": "user"}, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


@pytest.mark.asyncio
async def test_persist_text_happy_path(client, db_session):
    u = User(email="a@b.c", phone="+1000000008", password_hash="x",
            first_name=None, last_name=None, patronymic=None,
            referral_code="REF008", referrer_id=None)
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    cr = ChatRepository(db_session)
    chat = await cr.get_or_create_for_user(owner_user_id=u.id, chat_type="main")

    r = await client.post(
        f"/internal/chats/{chat.id}/messages",
        json={
            "user_id": f"user:{u.id}", "role": "user",
            "kind": "message", "body": "hi", "client_msg_id": "c-1",
        },
        headers={"X-Internal-Secret": settings.internal_secret},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "message" and body["body"] == "hi"
    assert body["user_id"] == f"user:{u.id}"
    assert body["client_msg_id"] == "c-1"


@pytest.mark.asyncio
async def test_persist_oversize_returns_413_envelope(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "max_message_bytes", 5)
    u = User(email="a@b.c", phone="+1000000009", password_hash="x",
            first_name=None, last_name=None, patronymic=None,
            referral_code="REF009", referrer_id=None)
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    cr = ChatRepository(db_session)
    chat = await cr.get_or_create_for_user(owner_user_id=u.id, chat_type="main")
    r = await client.post(
        f"/internal/chats/{chat.id}/messages",
        json={"user_id": f"user:{u.id}", "role": "user", "kind": "message", "body": "way too long"},
        headers={"X-Internal-Secret": settings.internal_secret},
    )
    assert r.status_code == 413
    assert r.json()["code"] == "payload_too_large"
