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
    confidence: float
    signal_bps: float
    adverse_risk_bps: float
    components: dict[str, float] = Field(default_factory=dict)


def _clamp_probability(value: float) -> float:
    return max(0.01, min(0.99, value))


def _clamp(value: float, *, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def compute_fair_value(inputs: FairValueInputs) -> FairValueDecision:
    best_bid = inputs.primary.best_bid or inputs.primary.best_ask or 0.5
    best_ask = inputs.primary.best_ask or inputs.primary.best_bid or 0.5
    midpoint = (best_bid + best_ask) / 2.0
    bid_size = max(inputs.primary.bid_size or 0.0, 0.0)
    ask_size = max(inputs.primary.ask_size or 0.0, 0.0)
    total_depth = bid_size + ask_size
    spread = max(best_ask - best_bid, 0.0)
    imbalance = ((bid_size - ask_size) / total_depth) if total_depth > 0 else 0.0
    microprice = ((best_ask * bid_size) + (best_bid * ask_size)) / total_depth if total_depth > 0 else midpoint
    relation_anchor = 1.0 - inputs.complementary_midpoint if inputs.complementary_midpoint is not None else midpoint
    last_trade_anchor = inputs.last_trade_price if inputs.last_trade_price is not None else midpoint
    micro_offset = microprice - midpoint
    relation_offset = relation_anchor - midpoint
    trade_offset = last_trade_anchor - midpoint
    relation_gap = abs(relation_offset)

    spread_score = max(0.0, 1.0 - min(spread, 0.20) / 0.20)
    depth_score = min(total_depth / 250.0, 1.0)
    consistency_score = max(0.0, 1.0 - min(relation_gap, 0.12) / 0.12)
    imbalance_score = max(0.0, 1.0 - min(abs(imbalance), 1.0))
    confidence = _clamp(
        0.20
        + (0.28 * spread_score)
        + (0.20 * depth_score)
        + (0.22 * consistency_score)
        + (0.10 * imbalance_score)
        - (0.35 * max(inputs.ambiguity_score, 0.0)),
        lower=0.15,
        upper=0.95,
    )

    weighted_offset = (0.45 * micro_offset) + (0.40 * relation_offset) + (0.15 * trade_offset)
    max_offset = max(spread * 1.5, 0.01) * (0.60 + (0.40 * confidence))
    anchored_offset = _clamp(
        weighted_offset * (0.50 + (0.50 * confidence)),
        lower=-max_offset,
        upper=max_offset,
    )

    inventory_adjustment = -0.02 * inputs.inventory_skew * (0.50 + (0.50 * confidence))
    ambiguity_adjustment = -0.01 * max(inputs.ambiguity_score, 0.0)
    reward_adjustment = 0.005 * max(inputs.reward_score, 0.0) * (0.5 - midpoint)
    fair_value = _clamp_probability(midpoint + anchored_offset + inventory_adjustment + ambiguity_adjustment + reward_adjustment)
    signal_bps = ((fair_value - midpoint) / max(midpoint, 0.05)) * 10_000.0
    adverse_risk_bps = max(
        4.0,
        (spread * 10_000.0 * (0.08 + (0.04 * (1.0 - confidence))))
        + (abs(imbalance) * 8.0)
        + (max(inputs.ambiguity_score, 0.0) * 80.0),
    )
    edge_buffer_bps = max(
        6.0,
        adverse_risk_bps
        + (abs(signal_bps) * 0.20)
        + (min(inputs.time_to_resolution_days, 90.0) * 0.02)
        - (max(inputs.reward_score, 0.0) * 4.0),
    )
    return FairValueDecision(
        fair_value=fair_value,
        midpoint=midpoint,
        microprice=microprice,
        edge_buffer_bps=edge_buffer_bps,
        confidence=round(confidence, 6),
        signal_bps=round(signal_bps, 6),
        adverse_risk_bps=round(adverse_risk_bps, 6),
        components={
            "spread": spread,
            "imbalance": imbalance,
            "relation_anchor": relation_anchor,
            "micro_offset": micro_offset,
            "relation_offset": relation_offset,
            "trade_offset": trade_offset,
            "anchored_offset": anchored_offset,
            "inventory_adjustment": inventory_adjustment,
            "ambiguity_adjustment": ambiguity_adjustment,
            "reward_adjustment": reward_adjustment,
        },
    )
