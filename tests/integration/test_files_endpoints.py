import io

import pytest

from app.core.config import settings
from app.models.users.entities import User
from app.repositories.chat_repository import ChatRepository
from app.services.auth_service import AuthService


@pytest.fixture
async def user_and_chat(db_session):
    u = User(email="a@b.c", phone="+1000000013", password_hash="x",
            first_name=None, last_name=None, patronymic=None,
            referral_code="REF013", referrer_id=None)
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    cr = ChatRepository(db_session)
    chat = await cr.get_or_create_for_user(owner_user_id=u.id, chat_type="main")
    svc = AuthService(db_session)
    token = svc._generate_access_token(user_id=u.id)
    return u, chat, token


@pytest.mark.asyncio
async def test_upload_then_download(client, user_and_chat, monkeypatch):
    user, chat, token = user_and_chat

    # Mock MinIO via app.state on the FastAPI instance.
    from app.main import app

    class FakeMinIO:
        def __init__(self):
            self.objects = {}
        def put_object(self, bucket, key, data, length, content_type=None):
            self.objects[(bucket, key)] = data.read() if hasattr(data, "read") else data
        def get_object(self, bucket, key):
            body = self.objects.get((bucket, key), b"")
            class _Resp:
                def __init__(self, b): self._b = b
                def stream(self, n): yield self._b
                def close(self): pass
                def release_conn(self): pass
            return _Resp(body)
        def remove_object(self, bucket, key):
            self.objects.pop((bucket, key), None)
        def bucket_exists(self, bucket): return True
        def make_bucket(self, bucket): pass

    fake = FakeMinIO()
    monkeypatch.setattr(app.state, "minio", fake, raising=False)
    monkeypatch.setattr(settings, "minio_bucket", "test-bucket")

    files = {"file": ("hi.pdf", io.BytesIO(b"hello"), "application/pdf")}
    data = {"chat_id": str(chat.id)}
    r = await client.post("/api/v1/files/", files=files, data=data,
                          headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "hi.pdf" and body["mime"] == "application/pdf" and body["size"] == 5
    file_id = body["file_id"]

    r2 = await client.get(f"/api/v1/files/{file_id}/", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200
    assert r2.headers["content-type"].startswith("application/pdf")
    assert r2.content == b"hello"


@pytest.mark.asyncio
async def test_upload_rejects_disallowed_type(client, user_and_chat, monkeypatch):
    _user, chat, token = user_and_chat

    from app.main import app
    monkeypatch.setattr(app.state, "minio", object(), raising=False)

    files = {"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")}
    data = {"chat_id": str(chat.id)}
    r = await client.post("/api/v1/files/", files=files, data=data,
                          headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 415, r.text
    body = r.json()
    assert body["code"] == "unsupported_file_type"
    assert "jpg, png, pdf, heic" in body["reason"]


@pytest.mark.asyncio
async def test_upload_allows_heic_with_octet_stream_mime(client, user_and_chat, monkeypatch):
    _user, chat, token = user_and_chat

    from app.main import app

    class FakeMinIO:
        def put_object(self, bucket, key, data, length, content_type=None): pass
        def bucket_exists(self, bucket): return True

    monkeypatch.setattr(app.state, "minio", FakeMinIO(), raising=False)

    files = {"file": ("photo.HEIC", io.BytesIO(b"x"), "application/octet-stream")}
    data = {"chat_id": str(chat.id)}
    r = await client.post("/api/v1/files/", files=files, data=data,
                          headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_upload_rejects_non_participant(client, user_and_chat, db_session, monkeypatch):
    user, chat, _token = user_and_chat
    # Make a second user and token.
    u2 = User(email="b@b.c", phone="+1000000014", password_hash="x",
            first_name=None, last_name=None, patronymic=None,
            referral_code="REF014", referrer_id=None)
    db_session.add(u2)
    await db_session.commit()
    await db_session.refresh(u2)
    svc = AuthService(db_session)
    other_token = svc._generate_access_token(user_id=u2.id)

    files = {"file": ("a.pdf", io.BytesIO(b"x"), "application/pdf")}
    data = {"chat_id": str(chat.id)}
    r = await client.post("/api/v1/files/", files=files, data=data,
                          headers={"Authorization": f"Bearer {other_token}"})
    assert r.status_code == 403
