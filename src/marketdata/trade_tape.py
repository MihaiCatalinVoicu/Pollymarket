from __future__ import annotations

from pydantic import BaseModel


class TradePrint(BaseModel):
    trade_id: str | None = None
    market_id: str
    asset_id: str
    price: float
    size: float
    side: str | None = None
    ts: str | None = None

