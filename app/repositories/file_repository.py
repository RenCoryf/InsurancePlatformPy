from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables.file import File


class FileRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        *,
        chat_id: UUID,
        uploader_subject_type: str,
        uploader_subject_id: int,
        original_name: str,
        mime_type: str,
        size_bytes: int,
        minio_key: str,
    ) -> File:
        f = File(
            chat_id=chat_id,
            uploader_subject_type=uploader_subject_type,
            uploader_subject_id=uploader_subject_id,
            original_name=original_name,
            mime_type=mime_type,
            size_bytes=size_bytes,
            minio_key=minio_key,
        )
        self._session.add(f)
        await self._session.flush()
        await self._session.refresh(f)
        return f

    async def get_by_id(self, file_id: UUID) -> File | None:
        row = await self._session.execute(select(File).where(File.id == file_id))
        return row.scalar_one_or_none()
