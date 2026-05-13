from fastapi import APIRouter
from pydantic import BaseModel

from app.api.utils import not_implemented


class PartnerResponse(BaseModel):
    id: str
    name: str
    status: str


router = APIRouter(prefix="/partners", tags=["partners"])


@router.get("/", response_model=list[PartnerResponse])
async def list_partners() -> list[PartnerResponse]:
    not_implemented("List active partners")


@router.get("/{partner_id}/", response_model=PartnerResponse)
async def get_partner(partner_id: str) -> PartnerResponse:
    not_implemented("Return partner details")
