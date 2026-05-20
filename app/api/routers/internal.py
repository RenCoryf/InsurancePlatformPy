from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.internal_secret import internal_secret_required
from app.core.database import get_async_session
from app.models.dto.internal import (
    PersistMessageRequest,
    WsValidateRequest,
    WsValidateResponse,
)
from app.models.dto.message import MessageResponse
from app.services.internal_service import InternalService


router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(internal_secret_required)])


@router.post("/auth/ws-validate", response_model=WsValidateResponse)
async def ws_validate(
    payload: WsValidateRequest,
    session: AsyncSession = Depends(get_async_session),
) -> WsValidateResponse:
    svc = InternalService(session)
    return await svc.ws_validate(token=payload.token, chat_type=payload.chat_type, chat_id_hint=payload.chat_id_hint)


@router.post("/chats/{chat_id}/messages", response_model=MessageResponse)
async def persist_message(
    chat_id: UUID,
    payload: PersistMessageRequest,
    session: AsyncSession = Depends(get_async_session),
) -> MessageResponse:
    svc = InternalService(session)
    return await svc.persist_message(
        chat_id=chat_id,
        user_id=payload.user_id,
        role=payload.role,
        kind=payload.kind,
        body=payload.body,
        file_id=payload.file_id,
        client_msg_id=payload.client_msg_id,
    )
