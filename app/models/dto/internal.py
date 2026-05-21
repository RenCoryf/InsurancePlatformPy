from uuid import UUID

from pydantic import BaseModel


class WsValidateRequest(BaseModel):
    token: str
    chat_type: str
    chat_id_hint: str = ""


class WsValidateResponse(BaseModel):
    user_id: str
    role: str
    chat_id: UUID


class PersistMessageRequest(BaseModel):
    user_id: str
    role: str
    kind: str
    body: str | None = None
    file_id: UUID | None = None
    client_msg_id: str | None = None
