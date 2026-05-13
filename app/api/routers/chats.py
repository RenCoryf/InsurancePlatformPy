from fastapi import APIRouter, status
from pydantic import BaseModel

from app.api.utils import not_implemented


class ChatCreate(BaseModel):
    type: str
    manager_id: str | None = None


class ChatResponse(BaseModel):
    id: str
    type: str


class MessageCreate(BaseModel):
    body: str


class MessageResponse(BaseModel):
    id: str
    body: str


router = APIRouter(prefix="/chats", tags=["chats"])


@router.get("/", response_model=list[ChatResponse])
async def list_chats() -> list[ChatResponse]:
    not_implemented("Return chats for the current user")


@router.post("/", response_model=ChatResponse, status_code=status.HTTP_201_CREATED)
async def create_chat(payload: ChatCreate) -> ChatResponse:
    not_implemented("Create or open a chat")


@router.get("/{chat_id}/messages/", response_model=list[MessageResponse])
async def list_messages(chat_id: str) -> list[MessageResponse]:
    not_implemented("List chat messages")


@router.post("/{chat_id}/messages/", response_model=MessageResponse)
async def post_message(chat_id: str, payload: MessageCreate) -> MessageResponse:
    not_implemented("Send chat message")


@router.post("/{chat_id}/read/", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(chat_id: str) -> None:
    not_implemented("Mark chat as read")


@router.get("/{chat_id}/files/")
async def list_chat_files(chat_id: str) -> list[str]:
    not_implemented("List files attached to chat")
