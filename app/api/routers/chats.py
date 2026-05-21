from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.subject_auth import SubjectRow, get_current_subject
from app.core.database import get_async_session
from app.models.dto.chat import ChatCreate, ChatResponse
from app.models.dto.file import FileMeta
from app.models.dto.message import MessageList, MessageResponse
from app.repositories.chat_repository import ChatRepository
from app.repositories.file_repository import FileRepository
from app.repositories.message_repository import MessageRepository


router = APIRouter(prefix="/chats", tags=["chats"])


@router.get("/", response_model=list[ChatResponse])
async def list_chats(
    subject: SubjectRow = Depends(get_current_subject),
    session: AsyncSession = Depends(get_async_session),
) -> list[ChatResponse]:
    if subject.subject.type != "user" or subject.user is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user only")
    repo = ChatRepository(session)
    # Lazy-create main if missing
    await repo.get_or_create_for_user(owner_user_id=subject.user.id, chat_type="main")
    rows = await repo.list_for_user(subject.user.id)
    return [ChatResponse(id=c.id, type=c.type, last_message_at=c.last_message_at) for c in rows]


@router.post("/", response_model=ChatResponse)
async def open_chat(
    payload: ChatCreate,
    subject: SubjectRow = Depends(get_current_subject),
    session: AsyncSession = Depends(get_async_session),
) -> ChatResponse:
    if subject.subject.type != "user" or subject.user is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user only")
    if payload.type not in {"main", "bonus"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid chat type")
    repo = ChatRepository(session)
    chat = await repo.get_or_create_for_user(owner_user_id=subject.user.id, chat_type=payload.type)
    return ChatResponse(id=chat.id, type=chat.type, last_message_at=chat.last_message_at)


@router.get("/{chat_id}/messages/", response_model=MessageList)
async def list_chat_messages(
    chat_id: UUID,
    before: UUID | None = Query(default=None),
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    subject: SubjectRow = Depends(get_current_subject),
    session: AsyncSession = Depends(get_async_session),
) -> MessageList:
    chat_repo = ChatRepository(session)
    chat = await chat_repo.get_by_id(chat_id)
    if chat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="chat not found")
    if subject.subject.type == "user":
        if subject.user is None or chat.owner_user_id != subject.user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not a participant")
    else:
        if subject.support is None or not subject.support.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="support inactive")

    msg_repo = MessageRepository(session)
    rows = await msg_repo.list_history(chat_id=chat_id, limit=limit, before_id=before)

    file_ids = {m.file_id for m in rows if m.file_id is not None}
    files = {}
    if file_ids:
        file_repo = FileRepository(session)
        for fid in file_ids:
            f = await file_repo.get_by_id(fid)
            if f is not None:
                files[f.id] = f

    items = []
    for m in rows:
        file_meta: FileMeta | None = None
        if m.kind == "file" and m.file_id is not None and m.file_id in files:
            f = files[m.file_id]
            file_meta = FileMeta(file_id=f.id, name=f.original_name, mime=f.mime_type, size=f.size_bytes,
                                 url=f"/api/v1/files/{f.id}/")
        items.append(MessageResponse(
            id=m.id, chat_id=m.chat_id,
            user_id=f"{m.sender_subject_type}:{m.sender_subject_id}",
            role=m.sender_subject_type,
            kind=m.kind, body=m.body, file=file_meta,
            client_msg_id=m.client_msg_id, created_at=m.created_at,
        ))

    next_cursor = rows[-1].id if len(rows) == limit else None
    return MessageList(messages=items, next_cursor=next_cursor)
