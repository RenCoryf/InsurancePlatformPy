from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class PartnerResponse(BaseModel):
    id: int
    name: str
    logo_file_key: str | None
    min_exchange: Decimal
    max_exchange: Decimal | None
    exchange_step: Decimal
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
