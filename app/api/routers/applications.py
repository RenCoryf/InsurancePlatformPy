from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.utils import not_implemented


class ApplicationDraft(BaseModel):
    product_code: str = Field(..., description="Product slug")
    comment: str | None = Field(None, max_length=1000)


class ApplicationResponse(BaseModel):
    id: str
    product_code: str
    status: str
    created_at: str


router = APIRouter(prefix="/applications", tags=["applications"])


@router.get("/", response_model=list[ApplicationResponse])
async def list_applications() -> list[ApplicationResponse]:
    not_implemented("List applications for current user or managers")


@router.post("/", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED)
async def create_application(payload: ApplicationDraft) -> ApplicationResponse:
    not_implemented("Create a new insurance application")


@router.get("/{application_id}/", response_model=ApplicationResponse)
async def get_application(application_id: str) -> ApplicationResponse:
    not_implemented("Fetch a single application")


@router.patch("/{application_id}/", response_model=ApplicationResponse)
async def update_application(application_id: str, payload: ApplicationDraft) -> ApplicationResponse:
    not_implemented("Update application status/comments")
