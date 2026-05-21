import pytest

from app.repositories.chat_repository import ChatRepository
from app.repositories.file_repository import FileRepository


@pytest.fixture
async def chat(db_session):
    from app.models.users.entities import User
    u = User(email="x@y.z", phone="+1000000003", password_hash="x",
            first_name=None, last_name=None, patronymic=None,
            referral_code="REF003", referrer_id=None)
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    repo = ChatRepository(db_session)
    return await repo.get_or_create_for_user(owner_user_id=u.id, chat_type="main")


@pytest.mark.asyncio
async def test_create_and_get(db_session, chat):
    repo = FileRepository(db_session)
    f = await repo.create(
        chat_id=chat.id, uploader_subject_type="user", uploader_subject_id=42,
        original_name="report.pdf", mime_type="application/pdf", size_bytes=12345,
        minio_key=f"chats/{chat.id}/test",
    )
    await db_session.commit()
    got = await repo.get_by_id(f.id)
    assert got is not None and got.original_name == "report.pdf"
