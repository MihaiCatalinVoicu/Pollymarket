from __future__ import annotations

import math

from pydantic import BaseModel


class OrderIntent(BaseModel):
    market_id: str
    asset_id: str
    side: str
    price: float
    size: float
    tif: str = "GTC"
    post_only: bool = True
    client_order_id: str | None = None


class RoutedOrder(BaseModel):
    accepted: bool
    reasons: list[str]
    payload: dict


class OrderRouter:
    def prepare_order(self, intent: OrderIntent, *, tick_size: float, best_bid: float | None = None, best_ask: float | None = None) -> RoutedOrder:
        reasons: list[str] = []
        if intent.size <= 0:
            reasons.append("non_positive_size")
        rounded_price = math.floor(intent.price / tick_size) * tick_size
        if abs(rounded_price - intent.price) > 1e-9:
            reasons.append("price_not_on_tick")
        if intent.post_only:
            if intent.side == "buy" and best_ask is not None and intent.price >= best_ask:
                reasons.append("post_only_would_cross")
            if intent.side == "sell" and best_bid is not None and intent.price <= best_bid:
                reasons.append("post_only_would_cross")
        return RoutedOrder(
            accepted=not reasons,
            reasons=reasons,
            payload={
                "market_id": intent.market_id,
                "asset_id": intent.asset_id,
                "side": intent.side,
                "price": rounded_price,
                "size": intent.size,
                "tif": intent.tif,
                "post_only": intent.post_only,
                "client_order_id": intent.client_order_id,
            },
        )

