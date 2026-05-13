from fastapi import APIRouter
from pydantic import BaseModel

from app.api.utils import not_implemented


class BalanceResponse(BaseModel):
    balance: float
    pending_amount: float


class BonusTransactionResponse(BaseModel):
    id: str
    amount: float
    status: str


router = APIRouter(prefix="/bonuses", tags=["bonuses"])


@router.get("/me/", response_model=list[BonusTransactionResponse])
async def my_bonuses() -> list[BonusTransactionResponse]:
    not_implemented("List bonus transactions for current user")


@router.get("/me/balance/", response_model=BalanceResponse)
async def my_balance() -> BalanceResponse:
    not_implemented("Return user balance and pending amount")


@router.get("/stats/")
async def bonus_stats() -> dict[str, str]:
    not_implemented("Aggregation of bonus accruals")
