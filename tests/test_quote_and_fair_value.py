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
    assert 0.15 <= neutral.confidence <= 0.95
    assert neutral.edge_buffer_bps >= 6.0


def test_quote_engine_never_crosses_book() -> None:
    quotes = build_quotes(
        QuoteRequest(
            fair_value=0.5,
            midpoint=0.5,
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


def test_one_sided_quotes_follow_signal_and_skip_neutral_setups() -> None:
    bullish = build_quotes(
        QuoteRequest(
            fair_value=0.56,
            midpoint=0.50,
            best_bid=0.49,
            best_ask=0.51,
            tick_size=0.01,
            base_size=20,
            min_size=5,
            edge_buffer_bps=20,
            quoting_mode="one_sided",
        )
    )
    bearish = build_quotes(
        QuoteRequest(
            fair_value=0.44,
            midpoint=0.50,
            best_bid=0.49,
            best_ask=0.51,
            tick_size=0.01,
            base_size=20,
            min_size=5,
            edge_buffer_bps=20,
            quoting_mode="one_sided",
        )
    )
    neutral = build_quotes(
        QuoteRequest(
            fair_value=0.5004,
            midpoint=0.50,
            best_bid=0.49,
            best_ask=0.51,
            tick_size=0.01,
            base_size=20,
            min_size=5,
            edge_buffer_bps=20,
            quoting_mode="one_sided",
        )
    )
    assert bullish and bullish[0].side == "buy"
    assert bearish and bearish[0].side == "sell"
    assert neutral == []
