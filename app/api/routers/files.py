from fastapi import APIRouter
from pydantic import BaseModel

from app.api.utils import not_implemented


class PresignRequest(BaseModel):
    filename: str
    content_type: str


class PresignResponse(BaseModel):
    url: str
    fields: dict[str, str]


router = APIRouter(prefix="/files", tags=["files"])


@router.post("/presign/", response_model=PresignResponse)
async def presign_file(payload: PresignRequest) -> PresignResponse:
    not_implemented("Generate presigned upload URL")


@router.get("/{file_id}/")
async def get_file_metadata(file_id: str) -> dict[str, str]:
    not_implemented("Return metadata and download url for stored file")
