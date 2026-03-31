from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel


def _floor_tick(value: float, tick_size: float) -> float:
    return math.floor(value / tick_size) * tick_size


def _ceil_tick(value: float, tick_size: float) -> float:
    return math.ceil(value / tick_size) * tick_size


class QuoteRequest(BaseModel):
    fair_value: float
    midpoint: float | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    tick_size: float
    base_size: float
    min_size: float
    max_width_bps: float = 100.0
    edge_buffer_bps: float = 10.0
    skew: float = 0.0
    quoting_mode: Literal["one_sided", "two_sided"] = "one_sided"


class QuoteIntent(BaseModel):
    side: Literal["buy", "sell"]
    price: float
    size: float
    tif: Literal["GTC", "GTD"] = "GTC"
    post_only: bool = True
    reason: str


def build_quotes(request: QuoteRequest) -> list[QuoteIntent]:
    tick = request.tick_size
    midpoint = request.midpoint if request.midpoint is not None else request.fair_value
    signal_bps = ((request.fair_value - midpoint) / max(midpoint, 0.05)) * 10_000.0
    width_bps = min(500.0, max(float(request.max_width_bps), 12.0, request.edge_buffer_bps * 0.15))
    width = max(tick * 2.0, max(request.fair_value, midpoint) * width_bps / 10000.0)
    raw_bid = _floor_tick(request.fair_value - (width / 2.0) - max(request.skew, 0.0) * tick, tick)
    raw_ask = _ceil_tick(request.fair_value + (width / 2.0) + max(-request.skew, 0.0) * tick, tick)
    if request.best_ask is not None and raw_bid >= request.best_ask:
        raw_bid = max(tick, _floor_tick(request.best_ask - tick, tick))
    if request.best_bid is not None and raw_ask <= request.best_bid:
        raw_ask = _ceil_tick(request.best_bid + tick, tick)
    buy_size = max(request.min_size, request.base_size * (1.0 - max(request.skew, 0.0) * 0.5))
    sell_size = max(request.min_size, request.base_size * (1.0 + min(request.skew, 0.0) * 0.5))
    if request.quoting_mode == "one_sided":
        if signal_bps >= request.edge_buffer_bps:
            return [QuoteIntent(side="buy", price=raw_bid, size=buy_size, reason="value_bid")]
        if signal_bps <= -request.edge_buffer_bps:
            return [QuoteIntent(side="sell", price=raw_ask, size=sell_size, reason="value_ask")]
        if request.skew >= 0.20:
            return [QuoteIntent(side="sell", price=raw_ask, size=sell_size, reason="inventory_relief")]
        if request.skew <= -0.20:
            return [QuoteIntent(side="buy", price=raw_bid, size=buy_size, reason="inventory_rebuild")]
        return []
    return [
        QuoteIntent(side="buy", price=raw_bid, size=buy_size, reason="two_sided_bid"),
        QuoteIntent(side="sell", price=raw_ask, size=sell_size, reason="two_sided_ask"),
    ]


def materially_changed(old: list[QuoteIntent], new: list[QuoteIntent], *, price_ticks: int = 2, size_delta_ratio: float = 0.20, tick_size: float) -> bool:
    if len(old) != len(new):
        return True
    keyed_old = {quote.side: quote for quote in old}
    keyed_new = {quote.side: quote for quote in new}
    if set(keyed_old) != set(keyed_new):
        return True
    for side, previous in keyed_old.items():
        current = keyed_new[side]
        if abs(previous.price - current.price) >= price_ticks * tick_size:
            return True
        if previous.size == 0:
            return True
        if abs(previous.size - current.size) / previous.size >= size_delta_ratio:
            return True
    return False
