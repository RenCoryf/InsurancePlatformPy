from datetime import datetime, timezone

import pytest
from passlib.context import CryptContext

from app.models.tables.support_agent import SupportAgent
from app.repositories.chat_repository import ChatRepository

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


@pytest.fixture
async def support_token(db_session, client):
    db_session.add(SupportAgent(login="ivy", password_hash=pwd.hash("openme"), display_name="Ivy", is_active=True))
    await db_session.commit()
    r = await client.post("/api/v1/support/login/", json={"login": "ivy", "password": "openme"})
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_support_chats_lists_active_chats(client, db_session, support_token):
    # Make a user and a chat with activity.
    from app.models.users.entities import User
    user = User(email="x@y.z", phone="+1000000004", password_hash="x",
                first_name="Alice", last_name="A.", patronymic=None,
                referral_code="REF004", referrer_id=None)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    cr = ChatRepository(db_session)
    chat = await cr.get_or_create_for_user(owner_user_id=user.id, chat_type="main")
    chat.last_message_at = datetime.now(timezone.utc)
    await db_session.commit()

    r = await client.get("/api/v1/support/chats/", headers={"Authorization": f"Bearer {support_token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(c["id"] == str(chat.id) for c in body["chats"])
    owner = next(c["owner"] for c in body["chats"] if c["id"] == str(chat.id))
    assert owner["phone"] == "+1000000004"


@pytest.mark.asyncio
async def test_support_chats_excludes_empty_by_default(client, db_session, support_token):
    from app.models.users.entities import User
    user = User(email="x@y.z", phone="+1000000005", password_hash="x",
                first_name=None, last_name=None, patronymic=None,
                referral_code="REF005", referrer_id=None)
    db_session.add(user)
    await db_session.commit()
    cr = ChatRepository(db_session)
    chat = await cr.get_or_create_for_user(owner_user_id=user.id, chat_type="main")
    # No bump → last_message_at is None

    r = await client.get("/api/v1/support/chats/", headers={"Authorization": f"Bearer {support_token}"})
    assert all(c["id"] != str(chat.id) for c in r.json()["chats"])
