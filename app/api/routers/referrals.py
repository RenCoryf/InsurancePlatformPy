from fastapi import APIRouter
from pydantic import BaseModel

from app.api.utils import not_implemented


class StructureSummary(BaseModel):
    levels: dict[str, int]
    total: int
    referral_link: str


class StructureMember(BaseModel):
    id: str
    full_name: str
    status: str
    joined_at: str


router = APIRouter(prefix="/referrals", tags=["referrals"])


@router.get("/me/structure/", response_model=StructureSummary)
async def structure_summary() -> StructureSummary:
    not_implemented("Return counts per level and referral link")


@router.get("/me/structure/list/", response_model=dict[str, list[StructureMember]])
async def structure_list() -> dict[str, list[StructureMember]]:
    not_implemented("Return detail list of structure members per level")


@router.get("/roots/")
async def referral_roots() -> list[str]:
    not_implemented("List live referral roots")
