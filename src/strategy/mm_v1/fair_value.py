from __future__ import annotations

from pydantic import BaseModel, Field


class BookSnapshot(BaseModel):
    best_bid: float | None = None
    best_ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None


class FairValueInputs(BaseModel):
    primary: BookSnapshot
    complementary_midpoint: float | None = None
    inventory_skew: float = 0.0
    ambiguity_score: float = 0.0
    reward_score: float = 0.0
    time_to_resolution_days: float = 30.0
    last_trade_price: float | None = None


class FairValueDecision(BaseModel):
    fair_value: float
    midpoint: float
    microprice: float
    edge_buffer_bps: float
    components: dict[str, float] = Field(default_factory=dict)


def _clamp_probability(value: float) -> float:
    return max(0.01, min(0.99, value))


def compute_fair_value(inputs: FairValueInputs) -> FairValueDecision:
    best_bid = inputs.primary.best_bid or inputs.primary.best_ask or 0.5
    best_ask = inputs.primary.best_ask or inputs.primary.best_bid or 0.5
    midpoint = (best_bid + best_ask) / 2.0
    bid_size = max(inputs.primary.bid_size or 0.0, 0.0)
    ask_size = max(inputs.primary.ask_size or 0.0, 0.0)
    microprice = ((best_ask * bid_size) + (best_bid * ask_size)) / (bid_size + ask_size) if bid_size + ask_size > 0 else midpoint
    relation_anchor = 1.0 - inputs.complementary_midpoint if inputs.complementary_midpoint is not None else midpoint
    base = (0.50 * microprice) + (0.35 * midpoint) + (0.15 * relation_anchor)
    if inputs.last_trade_price is not None:
        base = (0.80 * base) + (0.20 * inputs.last_trade_price)
    inventory_adjustment = -0.03 * inputs.inventory_skew
    ambiguity_adjustment = -0.02 * max(inputs.ambiguity_score, 0.0)
    reward_adjustment = 0.01 * max(inputs.reward_score, 0.0) * (0.5 - midpoint)
    fair_value = _clamp_probability(base + inventory_adjustment + ambiguity_adjustment + reward_adjustment)
    edge_buffer_bps = max(2.0, 8.0 + (inputs.ambiguity_score * 50.0) + min(inputs.time_to_resolution_days, 90.0) * 0.05 - (inputs.reward_score * 10.0))
    return FairValueDecision(
        fair_value=fair_value,
        midpoint=midpoint,
        microprice=microprice,
        edge_buffer_bps=edge_buffer_bps,
        components={
            "relation_anchor": relation_anchor,
            "inventory_adjustment": inventory_adjustment,
            "ambiguity_adjustment": ambiguity_adjustment,
            "reward_adjustment": reward_adjustment,
        },
    )

