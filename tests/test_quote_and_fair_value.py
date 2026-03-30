from __future__ import annotations

from src.strategy.mm_v1.fair_value import BookSnapshot, FairValueInputs, compute_fair_value
from src.strategy.mm_v1.quote_engine import QuoteRequest, build_quotes


def test_fair_value_penalizes_inventory_and_rewards_stay_bounded() -> None:
    neutral = compute_fair_value(
        FairValueInputs(primary=BookSnapshot(best_bid=0.49, best_ask=0.51, bid_size=100, ask_size=100))
    )
    skewed = compute_fair_value(
        FairValueInputs(
            primary=BookSnapshot(best_bid=0.49, best_ask=0.51, bid_size=100, ask_size=100),
            inventory_skew=0.8,
            reward_score=0.5,
        )
    )
    assert neutral.fair_value > skewed.fair_value
    assert 0.01 <= skewed.fair_value <= 0.99


def test_quote_engine_never_crosses_book() -> None:
    quotes = build_quotes(
        QuoteRequest(
            fair_value=0.5,
            best_bid=0.49,
            best_ask=0.51,
            tick_size=0.01,
            base_size=20,
            min_size=5,
            quoting_mode="two_sided",
        )
    )
    bid = next(item for item in quotes if item.side == "buy")
    ask = next(item for item in quotes if item.side == "sell")
    assert bid.price < 0.51
    assert ask.price > 0.49
    assert bid.price < ask.price

