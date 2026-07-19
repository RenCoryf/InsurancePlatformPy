from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ChatResponse(BaseModel):
    id: UUID
    type: str
    last_message_at: datetime | None


class ChatList(BaseModel):
    chats: list[ChatResponse]


class ChatCreate(BaseModel):
    type: str  # "main" | "bonus" — validated in the handler


class OwnerInfo(BaseModel):
    id: int
    phone: str
    first_name: str | None
    last_name: str | None


class SupportChatItem(BaseModel):
    id: UUID
    type: str
    owner: OwnerInfo
    last_message_at: datetime | None


class SupportChatList(BaseModel):
    chats: list[SupportChatItem]
    next_cursor: datetime | None
