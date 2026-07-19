from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables.file import File  # noqa: F401  ensure 'files' table is registered for FK resolution
from app.models.tables.message import Message


class MessageRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def insert_or_get(
        self,
        *,
        chat_id: UUID,
        sender_subject_type: str,
        sender_subject_id: int,
        kind: str,
        body: str | None,
        file_id: UUID | None,
        client_msg_id: str | None,
    ) -> tuple[Message, bool]:
        """Returns (row, created). Idempotent on (chat_id, client_msg_id)."""
        if client_msg_id is not None:
            existing = await self._session.execute(
                select(Message).where(Message.chat_id == chat_id, Message.client_msg_id == client_msg_id)
            )
            existing_row = existing.scalar_one_or_none()
            if existing_row is not None:
                return existing_row, False

        msg = Message(
            chat_id=chat_id,
            sender_subject_type=sender_subject_type,
            sender_subject_id=sender_subject_id,
            kind=kind,
            body=body,
            file_id=file_id,
            client_msg_id=client_msg_id,
        )
        self._session.add(msg)
        try:
            await self._session.flush()
        except Exception:
            await self._session.rollback()
            # Concurrent insert raced us — re-read.
            row = await self._session.execute(
                select(Message).where(Message.chat_id == chat_id, Message.client_msg_id == client_msg_id)
            )
            existing_row = row.scalar_one()
            return existing_row, False

        await self._session.refresh(msg)
        return msg, True

    async def list_history(
        self,
        *,
        chat_id: UUID,
        limit: int,
        before_id: UUID | None,
    ) -> list[Message]:
        """Returns up to `limit` rows ordered newest-first. If `before_id` is set,
        returns rows older than that message (cursor pagination)."""
        stmt = select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at.desc(), Message.id.desc()).limit(limit)
        if before_id is not None:
            cursor = await self._session.execute(select(Message).where(Message.id == before_id))
            cursor_row = cursor.scalar_one_or_none()
            if cursor_row is None:
                return []
            stmt = stmt.where(
                (Message.created_at < cursor_row.created_at)
                | ((Message.created_at == cursor_row.created_at) & (Message.id < cursor_row.id))
            )
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())

    async def get_by_id(self, message_id: UUID) -> Message | None:
        row = await self._session.execute(select(Message).where(Message.id == message_id))
        return row.scalar_one_or_none()

    async def delete(self, message: Message) -> None:
        await self._session.delete(message)
        await self._session.flush()
