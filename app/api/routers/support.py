from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.subject_auth import SubjectRow
from app.api.deps.support_auth import get_current_support
from app.core.database import get_async_session
from app.models.dto.chat import OwnerInfo, SupportChatItem, SupportChatList
from app.models.dto.support_agent import SupportLoginRequest, SupportTokenResponse
from app.models.users.entities import User
from app.repositories.chat_repository import ChatRepository
from app.services.support_auth_service import SupportAuthService


router = APIRouter(prefix="/support", tags=["support"])


@router.post("/login/", response_model=SupportTokenResponse)
async def support_login(
    payload: SupportLoginRequest,
    session: AsyncSession = Depends(get_async_session),
) -> SupportTokenResponse:
    svc = SupportAuthService(session)
    try:
        return await svc.login(payload.login, payload.password)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")


@router.get("/chats/", response_model=SupportChatList)
async def list_support_chats(
    chat_type: Annotated[str | None, Query(alias="type")] = None,
    before: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    include_empty: bool = Query(default=False),
    session: AsyncSession = Depends(get_async_session),
    _support: SubjectRow = Depends(get_current_support),
) -> SupportChatList:
    repo = ChatRepository(session)
    chats = await repo.list_active_for_support(
        chat_type=chat_type, limit=limit, before=before, include_empty=include_empty,
    )
    if not chats:
        return SupportChatList(chats=[], next_cursor=None)

    user_ids = {c.owner_user_id for c in chats}
    users_rows = await session.execute(select(User).where(User.id.in_(user_ids)))
    users = {u.id: u for u in users_rows.scalars().all()}

    items: list[SupportChatItem] = []
    for c in chats:
        u = users[c.owner_user_id]
        items.append(SupportChatItem(
            id=c.id, type=c.type,
            owner=OwnerInfo(id=u.id, phone=u.phone, first_name=u.first_name, last_name=u.last_name),
            last_message_at=c.last_message_at,
        ))

    next_cursor = chats[-1].last_message_at if len(chats) == limit else None
    return SupportChatList(chats=items, next_cursor=next_cursor)
