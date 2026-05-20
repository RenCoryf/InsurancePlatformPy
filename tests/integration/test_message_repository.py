import pytest

from app.repositories.chat_repository import ChatRepository
from app.repositories.message_repository import MessageRepository


@pytest.fixture
async def chat(db_session):
    from app.models.users.entities import User
    u = User(email="x@y.z", phone="+1000000002", password_hash="x", first_name=None, last_name=None,
            patronymic=None, referral_code="REF002", referrer_id=None)
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)

    repo = ChatRepository(db_session)
    return await repo.get_or_create_for_user(owner_user_id=u.id, chat_type="main")


@pytest.mark.asyncio
async def test_insert_and_get_existing(db_session, chat):
    repo = MessageRepository(db_session)
    msg, created = await repo.insert_or_get(
        chat_id=chat.id,
        sender_subject_type="user",
        sender_subject_id=42,
        kind="message",
        body="hello",
        file_id=None,
        client_msg_id="cli-1",
    )
    assert created is True

    msg2, created2 = await repo.insert_or_get(
        chat_id=chat.id,
        sender_subject_type="user",
        sender_subject_id=42,
        kind="message",
        body="hello",
        file_id=None,
        client_msg_id="cli-1",
    )
    assert created2 is False
    assert msg2.id == msg.id


@pytest.mark.asyncio
async def test_list_history_paginates(db_session, chat):
    repo = MessageRepository(db_session)
    ids = []
    for i in range(5):
        m, _ = await repo.insert_or_get(
            chat_id=chat.id, sender_subject_type="user", sender_subject_id=42,
            kind="message", body=f"m{i}", file_id=None, client_msg_id=f"c{i}",
        )
        ids.append(m.id)

    first_page = await repo.list_history(chat_id=chat.id, limit=3, before_id=None)
    assert len(first_page) == 3
    next_page = await repo.list_history(chat_id=chat.id, limit=3, before_id=first_page[-1].id)
    assert len(next_page) == 2
