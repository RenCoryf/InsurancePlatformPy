from uuid import UUID

from pydantic import BaseModel


class FileMeta(BaseModel):
    file_id: UUID
    name: str
    mime: str
    size: int
    url: str
