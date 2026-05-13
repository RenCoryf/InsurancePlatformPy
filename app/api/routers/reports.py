from fastapi import APIRouter, Response

from app.api.utils import not_implemented


router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/users-active.csv")
async def active_users_csv() -> Response:
    not_implemented("Return CSV of active users")


@router.get("/bonuses-by-month.csv")
async def bonuses_by_month_csv() -> Response:
    not_implemented("Return monthly bonus aggregation CSV")


@router.get("/certificates-by-status.csv")
async def certificates_by_status_csv() -> Response:
    not_implemented("Return certificate status CSV")
