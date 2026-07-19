from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.subject_auth import SubjectRow, get_current_subject
from app.core.config import settings
from app.core.database import get_async_session
from app.models.dto.file import FileMeta
from app.repositories.chat_repository import ChatRepository
from app.services.file_service import FileService


router = APIRouter(prefix="/files", tags=["files"])


@router.post("/", response_model=FileMeta, status_code=status.HTTP_201_CREATED)
async def upload_file(
    request: Request,
    chat_id: UUID = Form(...),
    file: UploadFile = File(...),
    subject: SubjectRow = Depends(get_current_subject),
    session: AsyncSession = Depends(get_async_session),
) -> FileMeta:
    # Authorize against chat.
    chat = await ChatRepository(session).get_by_id(chat_id)
    if chat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="chat not found")
    if subject.subject.type == "user":
        if subject.user is None or chat.owner_user_id != subject.user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not a participant")
    else:
        if subject.support is None or not subject.support.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="support inactive")

    minio_client = request.app.state.minio
    svc = FileService(session, minio_client, bucket=settings.minio_bucket, max_bytes=settings.max_file_bytes)

    # Determine declared size — UploadFile.size may be None if streamed; fall back to reading.
    size = file.size
    if size is None:
        body = await file.read()
        size = len(body)
        import io as _io
        stream = _io.BytesIO(body)
    else:
        stream = file.file

    f = await svc.upload(
        chat_id=chat_id,
        uploader_subject_type=subject.subject.type,
        uploader_subject_id=subject.subject.id,
        original_name=file.filename or "untitled",
        mime_type=file.content_type or "application/octet-stream",
        size_bytes=size,
        stream=stream,
    )
    return FileMeta(file_id=f.id, name=f.original_name, mime=f.mime_type, size=f.size_bytes,
                    url=f"/api/v1/files/{f.id}/")


@router.get("/{file_id}/")
async def download_file(
    file_id: UUID,
    request: Request,
    subject: SubjectRow = Depends(get_current_subject),
    session: AsyncSession = Depends(get_async_session),
) -> StreamingResponse:
    from app.repositories.file_repository import FileRepository
    f = await FileRepository(session).get_by_id(file_id)
    if f is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")

    chat = await ChatRepository(session).get_by_id(f.chat_id)
    if chat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="chat not found")
    if subject.subject.type == "user":
        if subject.user is None or chat.owner_user_id != subject.user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not a participant")
    else:
        if subject.support is None or not subject.support.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="support inactive")

    minio_client = request.app.state.minio
    svc = FileService(session, minio_client, bucket=settings.minio_bucket, max_bytes=settings.max_file_bytes)
    _, agen = await svc.download_stream(file_id)

    safe_name = f.original_name.replace('"', '')
    headers = {
        "Content-Length": str(f.size_bytes),
        "Content-Disposition": f'inline; filename="{safe_name}"',
        "Cache-Control": "private, max-age=0",
    }
    return StreamingResponse(agen, media_type=f.mime_type, headers=headers)
