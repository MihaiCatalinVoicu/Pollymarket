from __future__ import annotations

from src.strategy.latarb_v1.overlay import ActiveQuote, LatencyInputs, evaluate_latency_overlay
from src.strategy.parity_v1.engine import ParityInputs, compute_parity


def test_parity_flags_buy_full_set_and_merge() -> None:
    signal = compute_parity(
        ParityInputs(
            yes_bid=0.48,
            yes_ask=0.47,
            no_bid=0.47,
            no_ask=0.47,
            fee_rate=0.0,
            paired_inventory=10,
            book_unwind_value=0.92,
        )
    )
    assert signal.should_buy_full_set is True
    assert signal.should_merge_inventory is True


def test_latency_overlay_only_takes_when_not_blocked() -> None:
    blocked = evaluate_latency_overlay(
        LatencyInputs(
            prior_fair_value=0.50,
            new_fair_value=0.56,
            best_bid=0.54,
            best_ask=0.57,
            active_quotes=[ActiveQuote(quote_id="q1", side="buy", price=0.55)],
            fee_adjusted_edge=0.03,
            stale_take_enabled=True,
            risk_blocked=True,
        )
    )
    allowed = evaluate_latency_overlay(
        LatencyInputs(
            prior_fair_value=0.50,
            new_fair_value=0.56,
            best_bid=0.54,
            best_ask=0.57,
            active_quotes=[ActiveQuote(quote_id="q1", side="buy", price=0.55)],
            fee_adjusted_edge=0.03,
            stale_take_enabled=True,
            risk_blocked=False,
        )
    )
    assert blocked.should_stale_take is False
    assert allowed.should_stale_take is True
    assert "q1" in allowed.cancel_quote_ids

