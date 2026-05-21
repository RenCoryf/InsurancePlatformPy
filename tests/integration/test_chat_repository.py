import pytest

from app.repositories.chat_repository import ChatRepository


@pytest.fixture
async def real_user(db_session):
    """Insert a real user row so chat FK is satisfied."""
    from app.models.users.entities import User
    user = User(
        email="x@y.z", phone="+1000000001", password_hash="x",
        first_name="X", last_name="Y", patronymic=None,
        referral_code="REF001", referrer_id=None,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_get_or_create_lazy_creates_main(db_session, real_user):
    repo = ChatRepository(db_session)
    chat = await repo.get_or_create_for_user(owner_user_id=real_user.id, chat_type="main")
    assert chat.owner_user_id == real_user.id
    assert chat.type == "main"
    assert chat.id is not None


@pytest.mark.asyncio
async def test_get_or_create_is_idempotent(db_session, real_user):
    repo = ChatRepository(db_session)
    a = await repo.get_or_create_for_user(owner_user_id=real_user.id, chat_type="main")
    b = await repo.get_or_create_for_user(owner_user_id=real_user.id, chat_type="main")
    assert a.id == b.id


@pytest.mark.asyncio
async def test_get_by_id(db_session, real_user):
    repo = ChatRepository(db_session)
    created = await repo.get_or_create_for_user(owner_user_id=real_user.id, chat_type="bonus")
    found = await repo.get_by_id(created.id)
    assert found is not None and found.id == created.id


@pytest.mark.asyncio
async def test_list_for_user(db_session, real_user):
    repo = ChatRepository(db_session)
    await repo.get_or_create_for_user(owner_user_id=real_user.id, chat_type="main")
    await repo.get_or_create_for_user(owner_user_id=real_user.id, chat_type="bonus")
    rows = await repo.list_for_user(real_user.id)
    types = {c.type for c in rows}
    assert types == {"main", "bonus"}


@pytest.mark.asyncio
async def test_list_active_for_support(db_session, real_user):
    repo = ChatRepository(db_session)
    main = await repo.get_or_create_for_user(owner_user_id=real_user.id, chat_type="main")
    # Simulate activity by bumping last_message_at
    from datetime import datetime, timezone
    main.last_message_at = datetime.now(timezone.utc)
    await db_session.commit()

    rows = await repo.list_active_for_support(chat_type=None, limit=50, before=None, include_empty=False)
    assert any(c.id == main.id for c in rows)
