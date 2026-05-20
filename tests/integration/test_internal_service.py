import pytest
from jose import jwt

from app.core.config import settings
from app.models.tables.support_agent import SupportAgent
from app.models.users.entities import User
from app.repositories.chat_repository import ChatRepository
from app.services.internal_service import InternalService
from app.services.errors import ChatError


def _make_token(claims: dict) -> str:
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


@pytest.fixture
async def user(db_session):
    u = User(email="a@b.c", phone="+1000000006", password_hash="x",
            first_name=None, last_name=None, patronymic=None,
            referral_code="REF006", referrer_id=None)
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


@pytest.mark.asyncio
async def test_ws_validate_lazy_creates_main_chat_for_user(db_session, user):
    svc = InternalService(db_session)
    tok = _make_token({"sub": f"user:{user.id}", "role": "user"})
    res = await svc.ws_validate(token=tok, chat_type="main", chat_id_hint="")
    assert res.user_id == f"user:{user.id}"
    assert res.role == "user"
    assert res.chat_id is not None


@pytest.mark.asyncio
async def test_ws_validate_user_idempotent(db_session, user):
    svc = InternalService(db_session)
    tok = _make_token({"sub": f"user:{user.id}", "role": "user"})
    a = await svc.ws_validate(token=tok, chat_type="main", chat_id_hint="")
    b = await svc.ws_validate(token=tok, chat_type="main", chat_id_hint="")
    assert a.chat_id == b.chat_id


@pytest.mark.asyncio
async def test_ws_validate_support_with_unknown_chat_404(db_session):
    agent = SupportAgent(login="kim", password_hash="x", display_name="Kim", is_active=True)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    svc = InternalService(db_session)
    tok = _make_token({"sub": f"support:{agent.id}", "role": "support"})
    import uuid as _u
    with pytest.raises(ChatError) as ei:
        await svc.ws_validate(token=tok, chat_type="main", chat_id_hint=str(_u.uuid4()))
    assert ei.value.http_status == 404


@pytest.mark.asyncio
async def test_ws_validate_chat_type_mismatch_400(db_session, user):
    cr = ChatRepository(db_session)
    chat = await cr.get_or_create_for_user(owner_user_id=user.id, chat_type="main")
    agent = SupportAgent(login="leo", password_hash="x", display_name="Leo", is_active=True)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    svc = InternalService(db_session)
    tok = _make_token({"sub": f"support:{agent.id}", "role": "support"})
    with pytest.raises(ChatError) as ei:
        await svc.ws_validate(token=tok, chat_type="bonus", chat_id_hint=str(chat.id))
    assert ei.value.http_status == 400


@pytest.mark.asyncio
async def test_persist_message_text_creates_row_and_bumps_chat(db_session, user):
    cr = ChatRepository(db_session)
    chat = await cr.get_or_create_for_user(owner_user_id=user.id, chat_type="main")

    svc = InternalService(db_session)
    msg = await svc.persist_message(
        chat_id=chat.id,
        user_id=f"user:{user.id}",
        role="user",
        kind="message",
        body="hello",
        file_id=None,
        client_msg_id="c-1",
    )
    assert msg.kind == "message"
    assert msg.body == "hello"
    assert msg.user_id == f"user:{user.id}"

    refreshed = await cr.get_by_id(chat.id)
    assert refreshed.last_message_at is not None


@pytest.mark.asyncio
async def test_persist_message_idempotent_does_not_rebump(db_session, user):
    cr = ChatRepository(db_session)
    chat = await cr.get_or_create_for_user(owner_user_id=user.id, chat_type="main")
    svc = InternalService(db_session)
    a = await svc.persist_message(chat_id=chat.id, user_id=f"user:{user.id}", role="user",
                                  kind="message", body="x", file_id=None, client_msg_id="c-2")
    first_bump = (await cr.get_by_id(chat.id)).last_message_at
    b = await svc.persist_message(chat_id=chat.id, user_id=f"user:{user.id}", role="user",
                                  kind="message", body="x", file_id=None, client_msg_id="c-2")
    second_bump = (await cr.get_by_id(chat.id)).last_message_at
    assert a.id == b.id
    assert first_bump == second_bump


@pytest.mark.asyncio
async def test_persist_oversize_body_413(db_session, user, monkeypatch):
    monkeypatch.setattr(settings, "max_message_bytes", 10)
    cr = ChatRepository(db_session)
    chat = await cr.get_or_create_for_user(owner_user_id=user.id, chat_type="main")
    svc = InternalService(db_session)
    with pytest.raises(ChatError) as ei:
        await svc.persist_message(chat_id=chat.id, user_id=f"user:{user.id}", role="user",
                                  kind="message", body="x" * 11, file_id=None, client_msg_id="c-3")
    assert ei.value.http_status == 413
    assert ei.value.code == "payload_too_large"


@pytest.mark.asyncio
async def test_persist_file_not_in_chat_400(db_session, user):
    """file_id exists, but bound to a *different* chat → 400 validation."""
    from app.repositories.file_repository import FileRepository

    cr = ChatRepository(db_session)
    chat_a = await cr.get_or_create_for_user(owner_user_id=user.id, chat_type="main")
    chat_b = await cr.get_or_create_for_user(owner_user_id=user.id, chat_type="bonus")

    fr = FileRepository(db_session)
    file_b = await fr.create(
        chat_id=chat_b.id, uploader_subject_type="user", uploader_subject_id=user.id,
        original_name="x.txt", mime_type="text/plain", size_bytes=1,
        minio_key=f"chats/{chat_b.id}/k",
    )
    await db_session.commit()

    svc = InternalService(db_session)
    with pytest.raises(ChatError) as ei:
        await svc.persist_message(
            chat_id=chat_a.id, user_id=f"user:{user.id}", role="user",
            kind="file", body=None, file_id=file_b.id, client_msg_id="c-4",
        )
    assert ei.value.http_status == 400
    assert "file not in chat" in ei.value.reason
