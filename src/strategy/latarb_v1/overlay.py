from __future__ import annotations

from pydantic import BaseModel, Field


class ActiveQuote(BaseModel):
    quote_id: str
    side: str
    price: float


class LatencyInputs(BaseModel):
    prior_fair_value: float
    new_fair_value: float
    best_bid: float | None = None
    best_ask: float | None = None
    active_quotes: list[ActiveQuote] = Field(default_factory=list)
    fee_adjusted_edge: float = 0.0
    inventory_blocked: bool = False
    risk_blocked: bool = False
    min_reprice_move: float = 0.01
    min_take_edge: float = 0.02
    stale_take_enabled: bool = False


class LatencyDecision(BaseModel):
    cancel_quote_ids: list[str] = Field(default_factory=list)
    should_reprice: bool = False
    should_stale_take: bool = False
    reason: str = ""


def evaluate_latency_overlay(inputs: LatencyInputs) -> LatencyDecision:
    fv_shift = abs(inputs.new_fair_value - inputs.prior_fair_value)
    stale_quote_ids: list[str] = []
    for quote in inputs.active_quotes:
        if quote.side == "buy" and inputs.best_ask is not None and quote.price >= inputs.best_ask:
            stale_quote_ids.append(quote.quote_id)
        if quote.side == "sell" and inputs.best_bid is not None and quote.price <= inputs.best_bid:
            stale_quote_ids.append(quote.quote_id)
        if quote.side == "buy" and quote.price > inputs.new_fair_value:
            stale_quote_ids.append(quote.quote_id)
        if quote.side == "sell" and quote.price < inputs.new_fair_value:
            stale_quote_ids.append(quote.quote_id)
    stale_quote_ids = list(dict.fromkeys(stale_quote_ids))
    should_reprice = fv_shift >= inputs.min_reprice_move or bool(stale_quote_ids)
    if should_reprice and not stale_quote_ids:
        stale_quote_ids = [quote.quote_id for quote in inputs.active_quotes]
    can_take = (
        inputs.stale_take_enabled
        and not inputs.inventory_blocked
        and not inputs.risk_blocked
        and inputs.fee_adjusted_edge >= inputs.min_take_edge
        and fv_shift >= inputs.min_reprice_move
    )
    if can_take:
        reason = "stale_take_enabled"
    elif should_reprice:
        reason = "reprice_quotes"
    else:
        reason = "hold_quotes"
    return LatencyDecision(
        cancel_quote_ids=stale_quote_ids,
        should_reprice=should_reprice,
        should_stale_take=can_take,
        reason=reason,
    )
