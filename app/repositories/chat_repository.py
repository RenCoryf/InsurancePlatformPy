from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables.chat import Chat


class ChatRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_or_create_for_user(self, *, owner_user_id: int, chat_type: str) -> Chat:
        """Idempotent under the UNIQUE(owner_user_id, type) constraint."""
        stmt = (
            pg_insert(Chat)
            .values(owner_user_id=owner_user_id, type=chat_type)
            .on_conflict_do_nothing(index_elements=["owner_user_id", "type"])
            .returning(Chat.id)
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        inserted_id = result.scalar_one_or_none()
        if inserted_id is None:
            existing = await self._session.execute(
                select(Chat).where(Chat.owner_user_id == owner_user_id, Chat.type == chat_type)
            )
            chat = existing.scalar_one()
        else:
            existing = await self._session.execute(select(Chat).where(Chat.id == inserted_id))
            chat = existing.scalar_one()
        return chat

    async def get_by_id(self, chat_id: UUID) -> Chat | None:
        row = await self._session.execute(select(Chat).where(Chat.id == chat_id))
        return row.scalar_one_or_none()

    async def list_for_user(self, owner_user_id: int) -> list[Chat]:
        rows = await self._session.execute(
            select(Chat).where(Chat.owner_user_id == owner_user_id).order_by(Chat.type)
        )
        return list(rows.scalars().all())

    async def list_active_for_support(
        self,
        *,
        chat_type: str | None,
        limit: int,
        before: datetime | None,
        include_empty: bool,
    ) -> list[Chat]:
        stmt = select(Chat).order_by(Chat.last_message_at.desc().nullslast(), Chat.id).limit(limit)
        if chat_type is not None:
            stmt = stmt.where(Chat.type == chat_type)
        if not include_empty:
            stmt = stmt.where(Chat.last_message_at.is_not(None))
        if before is not None:
            stmt = stmt.where(Chat.last_message_at < before)
        rows = await self._session.execute(stmt)
        return list(rows.scalars().all())

    async def bump_last_message_at(self, chat_id: UUID) -> None:
        await self._session.execute(
            Chat.__table__.update().where(Chat.id == chat_id).values(last_message_at=func.now())
        )
