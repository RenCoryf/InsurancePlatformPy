from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.api.utils import not_implemented


class DealStatusUpdate(BaseModel):
    status: str
    comment: str | None = None


class DealResponse(BaseModel):
    id: str
    product_code: str
    amount: float
    status: str


class DealStatusEventResponse(BaseModel):
    id: str
    from_status: str
    to_status: str
    comment: str | None


router = APIRouter(prefix="/deals", tags=["deals"])


@router.get("/", response_model=list[DealResponse])
async def list_deals() -> list[DealResponse]:
    not_implemented("List deals with filters")


@router.get("/{deal_id}/", response_model=DealResponse)
async def get_deal(deal_id: str) -> DealResponse:
    not_implemented("Retrieve deal details")


@router.patch("/{deal_id}/status/", response_model=DealResponse)
async def update_deal_status(deal_id: str, payload: DealStatusUpdate) -> DealResponse:
    not_implemented("Transition deal status")


@router.get("/{deal_id}/events/", response_model=list[DealStatusEventResponse])
async def deal_events(deal_id: str) -> list[DealStatusEventResponse]:
    not_implemented("List deal status history")
