import asyncio
import uuid
from typing import BinaryIO

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables.file import File
from app.repositories.file_repository import FileRepository
from app.services.errors import ChatError

# ТЗ п. 8.3: в чат допускаются только jpg, png, pdf, heic.
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "pdf", "heic"}
ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "application/pdf",
    "image/heic",
    "image/heif",
    # Браузер может не знать тип (типично для heic) и прислать octet-stream —
    # тогда решает расширение.
    "application/octet-stream",
}
UNSUPPORTED_FILE_MESSAGE = "Недопустимый формат файла. Разрешены: jpg, png, pdf, heic"


class FileService:
    def __init__(self, session: AsyncSession, minio_client, bucket: str, max_bytes: int):
        self._session = session
        self._minio = minio_client
        self._bucket = bucket
        self._max_bytes = max_bytes

    async def upload(
        self,
        *,
        chat_id: uuid.UUID,
        uploader_subject_type: str,
        uploader_subject_id: int,
        original_name: str,
        mime_type: str,
        size_bytes: int,
        stream: BinaryIO,
    ) -> File:
        ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
        if ext not in ALLOWED_EXTENSIONS or mime_type not in ALLOWED_MIME_TYPES:
            raise ChatError("unsupported_file_type", UNSUPPORTED_FILE_MESSAGE, http_status=415)
        if size_bytes > self._max_bytes:
            raise ChatError("payload_too_large", "file exceeds max_file_bytes", http_status=413)

        file_id = uuid.uuid4()
        minio_key = f"chats/{chat_id}/{file_id}"

        # Streaming put — synchronous SDK; run in threadpool.
        await asyncio.to_thread(
            self._minio.put_object, self._bucket, minio_key, stream, size_bytes, content_type=mime_type,
        )

        try:
            repo = FileRepository(self._session)
            f = await repo.create(
                chat_id=chat_id,
                uploader_subject_type=uploader_subject_type,
                uploader_subject_id=uploader_subject_id,
                original_name=original_name,
                mime_type=mime_type,
                size_bytes=size_bytes,
                minio_key=minio_key,
            )
            # Override default UUID with our pre-generated one for predictable key
            f.id = file_id
            await self._session.commit()
            await self._session.refresh(f)
            return f
        except Exception:
            await self._session.rollback()
            try:
                await asyncio.to_thread(self._minio.remove_object, self._bucket, minio_key)
            except Exception:
                pass
            raise

    async def download_stream(self, file_id: uuid.UUID):
        """Returns (file_row, generator). Caller iterates the generator to stream bytes."""
        repo = FileRepository(self._session)
        f = await repo.get_by_id(file_id)
        if f is None:
            raise ChatError("validation", "file not found", http_status=404)
        # Open the MinIO response synchronously; the iterator yields chunks.
        response = await asyncio.to_thread(self._minio.get_object, self._bucket, f.minio_key)

        async def _agen():
            try:
                for chunk in response.stream(8 * 1024):
                    yield chunk
            finally:
                response.close()
                response.release_conn()

        return f, _agen()
