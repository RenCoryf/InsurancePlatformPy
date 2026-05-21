import pytest
from jose import jwt

from app.core.config import settings
from app.models.users.entities import User
from app.services.auth_service import AuthService


@pytest.fixture
async def user_with_token(db_session, client):
    u = User(email="a@b.c", phone="+1000000010", password_hash="x",
            first_name=None, last_name=None, patronymic=None,
            referral_code="REF010", referrer_id=None)
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)

    svc = AuthService(db_session)
    token = svc._generate_access_token(user_id=u.id)
    return u, token


@pytest.mark.asyncio
async def test_list_chats_lazy_creates_main(user_with_token, client):
    user, token = user_with_token
    r = await client.get("/api/v1/chats/", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    types = {c["type"] for c in body}
    assert "main" in types


@pytest.mark.asyncio
async def test_post_chats_opens_bonus(user_with_token, client):
    user, token = user_with_token
    r = await client.post("/api/v1/chats/", json={"type": "bonus"}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201 or r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "bonus"

    # GET now returns both.
    r2 = await client.get("/api/v1/chats/", headers={"Authorization": f"Bearer {token}"})
    types = {c["type"] for c in r2.json()}
    assert types == {"main", "bonus"}


@pytest.mark.asyncio
async def test_history_cursor_pagination(user_with_token, client, db_session):
    user, token = user_with_token
    from app.repositories.chat_repository import ChatRepository
    from app.repositories.message_repository import MessageRepository
    cr = ChatRepository(db_session)
    chat = await cr.get_or_create_for_user(owner_user_id=user.id, chat_type="main")
    mr = MessageRepository(db_session)
    ids = []
    for i in range(5):
        m, _ = await mr.insert_or_get(
            chat_id=chat.id, sender_subject_type="user", sender_subject_id=user.id,
            kind="message", body=f"m{i}", file_id=None, client_msg_id=f"c{i}",
        )
        ids.append(str(m.id))
    await db_session.commit()

    r = await client.get(
        f"/api/v1/chats/{chat.id}/messages/?limit=3",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["messages"]) == 3
    assert body["next_cursor"] is not None

    r2 = await client.get(
        f"/api/v1/chats/{chat.id}/messages/?limit=3&before={body['next_cursor']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert len(r2.json()["messages"]) == 2
    assert r2.json()["next_cursor"] is None


@pytest.mark.asyncio
async def test_history_rejects_non_owner(user_with_token, client, db_session):
    user, token = user_with_token
    # Make a second user with their own chat.
    u2 = User(email="b@b.c", phone="+1000000011", password_hash="x",
            first_name=None, last_name=None, patronymic=None,
            referral_code="REF011", referrer_id=None)
    db_session.add(u2)
    await db_session.commit()
    await db_session.refresh(u2)
    from app.repositories.chat_repository import ChatRepository
    cr = ChatRepository(db_session)
    other_chat = await cr.get_or_create_for_user(owner_user_id=u2.id, chat_type="main")

    r = await client.get(
        f"/api/v1/chats/{other_chat.id}/messages/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
