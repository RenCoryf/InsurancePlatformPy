import io

import pytest
from unittest.mock import MagicMock

from app.repositories.chat_repository import ChatRepository
from app.services.errors import ChatError
from app.services.file_service import FileService


class FakeMinIO:
    def __init__(self):
        self.put_calls = []
        self.objects = {}

    def put_object(self, bucket, key, data, length, content_type=None):
        self.put_calls.append((bucket, key, length, content_type))
        self.objects[(bucket, key)] = data.read() if hasattr(data, "read") else data

    def get_object(self, bucket, key):
        body = self.objects.get((bucket, key), b"")

        class _Resp:
            def __init__(self, b): self._b = b; self.headers = {}
            def stream(self, n): yield self._b
            def read(self, n=-1): return self._b
            def close(self): pass
            def release_conn(self): pass

        return _Resp(body)

    def remove_object(self, bucket, key):
        self.objects.pop((bucket, key), None)


@pytest.fixture
async def chat_and_user(db_session):
    from app.models.users.entities import User
    u = User(email="a@b.c", phone="+1000000012", password_hash="x",
            first_name=None, last_name=None, patronymic=None,
            referral_code="REF012", referrer_id=None)
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    cr = ChatRepository(db_session)
    chat = await cr.get_or_create_for_user(owner_user_id=u.id, chat_type="main")
    return chat, u


@pytest.mark.asyncio
async def test_upload_creates_row_and_puts_object(db_session, chat_and_user):
    chat, user = chat_and_user
    fake = FakeMinIO()
    svc = FileService(db_session, fake, bucket="chat-files-test", max_bytes=10_000)
    data = io.BytesIO(b"abc")
    f = await svc.upload(
        chat_id=chat.id, uploader_subject_type="user", uploader_subject_id=user.id,
        original_name="hello.txt", mime_type="text/plain", size_bytes=3, stream=data,
    )
    assert f.minio_key.startswith(f"chats/{chat.id}/")
    assert len(fake.put_calls) == 1


@pytest.mark.asyncio
async def test_upload_too_large_413(db_session, chat_and_user):
    chat, user = chat_and_user
    fake = FakeMinIO()
    svc = FileService(db_session, fake, bucket="b", max_bytes=2)
    with pytest.raises(ChatError) as ei:
        await svc.upload(
            chat_id=chat.id, uploader_subject_type="user", uploader_subject_id=user.id,
            original_name="big.bin", mime_type="application/octet-stream", size_bytes=10, stream=io.BytesIO(b"x" * 10),
        )
    assert ei.value.http_status == 413


@pytest.mark.asyncio
async def test_upload_db_failure_cleans_minio_object(db_session, chat_and_user, monkeypatch):
    """If the DB INSERT raises after MinIO put, the object must be removed."""
    chat, user = chat_and_user
    fake = FakeMinIO()
    svc = FileService(db_session, fake, bucket="b", max_bytes=10_000)

    # Force FileRepository.create to raise after MinIO put.
    from app.repositories import file_repository as fr_mod

    async def boom(self, **kw):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(fr_mod.FileRepository, "create", boom)

    with pytest.raises(RuntimeError):
        await svc.upload(
            chat_id=chat.id, uploader_subject_type="user", uploader_subject_id=user.id,
            original_name="x.txt", mime_type="text/plain", size_bytes=3, stream=io.BytesIO(b"abc"),
        )
    assert fake.objects == {}  # MinIO cleaned up
