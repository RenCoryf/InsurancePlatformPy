from uuid import UUID

from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.subject_auth import parse_subject_claim
from app.core.config import settings
from app.models.dto.file import FileMeta
from app.models.dto.internal import WsValidateResponse
from app.models.dto.message import MessageResponse
from app.models.tables.support_agent import SupportAgent
from app.models.users.entities import User
from app.repositories.chat_repository import ChatRepository
from app.repositories.file_repository import FileRepository
from app.repositories.message_repository import MessageRepository
from app.services.errors import ChatError
from app.services.notification_service import NotificationService


_VALID_CHAT_TYPES = {"main", "bonus"}
_VALID_KINDS = {"message", "file"}


class InternalService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def ws_validate(self, *, token: str, chat_type: str, chat_id_hint: str) -> WsValidateResponse:
        try:
            payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        except JWTError as e:
            raise ChatError("validation", f"invalid token: {e}", http_status=401)

        sub_claim = payload.get("sub")
        if not isinstance(sub_claim, str):
            raise ChatError("validation", "missing sub claim", http_status=401)
        try:
            subject = parse_subject_claim(sub_claim)
        except ValueError as e:
            raise ChatError("validation", str(e), http_status=401)

        if chat_type not in _VALID_CHAT_TYPES:
            raise ChatError("validation", f"invalid chat_type: {chat_type!r}", http_status=400)

        if subject.type == "user":
            row = await self._session.execute(select(User).where(User.id == subject.id))
            if row.scalar_one_or_none() is None:
                raise ChatError("validation", "user not found", http_status=401)

            cr = ChatRepository(self._session)
            chat = await cr.get_or_create_for_user(owner_user_id=subject.id, chat_type=chat_type)
            return WsValidateResponse(user_id=sub_claim, role="user", chat_id=chat.id)

        # subject.type == "support"
        row = await self._session.execute(select(SupportAgent).where(SupportAgent.id == subject.id))
        agent = row.scalar_one_or_none()
        if agent is None or not agent.is_active:
            raise ChatError("validation", "support agent not found or inactive", http_status=401)

        if not chat_id_hint:
            raise ChatError("validation", "chat_id_hint required for support", http_status=400)
        try:
            hint_uuid = UUID(chat_id_hint)
        except ValueError:
            raise ChatError("validation", "chat_id_hint not a UUID", http_status=400)

        cr = ChatRepository(self._session)
        chat = await cr.get_by_id(hint_uuid)
        if chat is None:
            # 401 so Go's pyclient maps to ErrUnauthorized (it only treats 401/403
            # as auth failures; other codes become 5xx in the gateway).
            raise ChatError("validation", "chat not found", http_status=401)
        if chat.type != chat_type:
            raise ChatError("validation", "chat_type mismatch", http_status=400)
        return WsValidateResponse(user_id=sub_claim, role="support", chat_id=chat.id)

    async def persist_message(
        self,
        *,
        chat_id: UUID,
        user_id: str,
        role: str,
        kind: str,
        body: str | None,
        file_id: UUID | None,
        client_msg_id: str | None,
    ) -> MessageResponse:
        # Parse and verify subject.
        try:
            subject = parse_subject_claim(user_id)
        except ValueError as e:
            raise ChatError("validation", str(e), http_status=401)

        if kind not in _VALID_KINDS:
            raise ChatError("unsupported_type", f"unknown kind: {kind!r}", http_status=400)

        cr = ChatRepository(self._session)
        chat = await cr.get_by_id(chat_id)
        if chat is None:
            raise ChatError("validation", "chat not found", http_status=404)

        agent: SupportAgent | None = None
        if subject.type == "user":
            if chat.owner_user_id != subject.id:
                raise ChatError("validation", "not a participant", http_status=403)
        else:
            row = await self._session.execute(select(SupportAgent).where(SupportAgent.id == subject.id))
            agent = row.scalar_one_or_none()
            if agent is None or not agent.is_active:
                raise ChatError("validation", "support agent inactive", http_status=403)

        # Per-kind validation.
        if kind == "message":
            if not body:
                raise ChatError("validation", "body required for kind=message", http_status=400)
            if len(body.encode("utf-8")) > settings.max_message_bytes:
                raise ChatError("payload_too_large", "body exceeds max_message_bytes", http_status=413)
            file_id = None
        else:  # kind == "file"
            if file_id is None:
                raise ChatError("validation", "file_id required for kind=file", http_status=400)
            file_row = await FileRepository(self._session).get_by_id(file_id)
            if file_row is None or file_row.chat_id != chat_id:
                raise ChatError("validation", "file not in chat", http_status=400)
            body = None

        msg_repo = MessageRepository(self._session)
        msg, created = await msg_repo.insert_or_get(
            chat_id=chat_id,
            sender_subject_type=subject.type,
            sender_subject_id=subject.id,
            kind=kind,
            body=body,
            file_id=file_id,
            client_msg_id=client_msg_id,
        )
        if created:
            await cr.bump_last_message_at(chat_id)
            # Сообщение от менеджера владельцу чата — SMS в очередь
            # (получатель мог быть офлайн; дневной лимит соблюдает sms_job).
            if agent is not None:
                await NotificationService(self._session).send(
                    chat.owner_user_id,
                    "chat_new_message",
                    {"sender": agent.display_name},
                )
        await self._session.commit()
        if created:
            await self._session.refresh(chat)

        # Build response.
        file_meta: FileMeta | None = None
        if msg.kind == "file":
            file_row = await FileRepository(self._session).get_by_id(msg.file_id)
            assert file_row is not None
            file_meta = FileMeta(
                file_id=file_row.id, name=file_row.original_name,
                mime=file_row.mime_type, size=file_row.size_bytes,
                url=f"/api/v1/files/{file_row.id}/",
            )

        return MessageResponse(
            id=msg.id, chat_id=msg.chat_id, user_id=user_id, role=role,
            kind=msg.kind, body=msg.body, file=file_meta,
            client_msg_id=msg.client_msg_id, created_at=msg.created_at,
        )
