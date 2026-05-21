from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.dto.file import FileMeta


class MessageResponse(BaseModel):
    id: UUID
    chat_id: UUID
    user_id: str
    role: str
    kind: str
    body: str | None = None
    file: FileMeta | None = None
    client_msg_id: str | None = None
    created_at: datetime


class MessageList(BaseModel):
    messages: list[MessageResponse]
    next_cursor: UUID | None
