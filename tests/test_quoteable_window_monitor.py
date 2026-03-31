from __future__ import annotations

from datetime import date, datetime, timezone

from src.config import Settings
from src.registry.models import MarketRecord, RewardConfig, RulesVersion
from src.shadow.service import ShadowAConfig, ShadowMarketState, StaticMarketStateProvider, TokenShadowState
from src.shadow.window_monitor import (
    QuoteableMarketObservation,
    QuoteableWindowSample,
    run_quoteable_window_monitor,
    sample_quoteable_window,
    summarize_quoteable_samples,
)


def _market_record(market_id: str, title: str, *, category: str | None = "crypto") -> MarketRecord:
    return MarketRecord(
        event_id=f"event-{market_id}",
        market_id=market_id,
        slug=market_id,
        title=title,
        category=category,
        tags=[category] if category else ["featured"],
        question_id=f"q-{market_id}",
        condition_id=f"c-{market_id}",
        token_ids=[f"{market_id}-yes", f"{market_id}-no"],
        outcomes=["Yes", "No"],
        active=True,
        closed=False,
        resolved=False,
        enable_order_book=True,
        fees_enabled=True,
        neg_risk=False,
        neg_risk_augmented=False,
        open_interest=12_000.0,
        volume_24h=3_000.0,
        tick_size=0.01,
        close_date=date(2026, 6, 30),
        rules=RulesVersion(
            rules_text="Resolves yes if the objective event occurs by the listed deadline using the stated source.",
            rules_hash=f"hash-{market_id}",
            resolution_source="official",
        ),
        reward_config=RewardConfig(
            min_incentive_size=5.0,
            max_incentive_spread=80.0,
            reward_allocation=60.0,
        ),
    )


def _market_state(market_id: str, *, bid: float, ask: float) -> ShadowMarketState:
    midpoint = round((bid + ask) / 2.0, 4)
    return ShadowMarketState(
        market_id=market_id,
        title=market_id,
        category="crypto",
        tick_size=0.01,
        primary=TokenShadowState(
            token_id=f"{market_id}-yes",
            outcome="Yes",
            best_bid=bid,
            best_ask=ask,
            bid_size=20.0,
            ask_size=18.0,
            midpoint=midpoint,
            last_trade_price=midpoint,
        ),
        complementary=TokenShadowState(
            token_id=f"{market_id}-no",
            outcome="No",
            best_bid=1.0 - ask,
            best_ask=1.0 - bid,
            bid_size=22.0,
            ask_size=19.0,
            midpoint=round(1.0 - midpoint, 4),
            last_trade_price=round(1.0 - midpoint, 4),
        ),
        fee_rate_bps=2.0,
        reward_config=RewardConfig(
            min_incentive_size=5.0,
            max_incentive_spread=80.0,
            reward_allocation=60.0,
        ),
        time_to_resolution_days=45.0,
        rules_ambiguity_score=0.02,
        open_interest=12_000.0,
        volume_24h=3_000.0,
    )


def test_sample_quoteable_window_collects_quoteable_and_rejections() -> None:
    records = [
        _market_record("narrow", "Will BTC be above 120k on June 30?"),
        _market_record("wide", "Will ETH be above 10k on June 30?"),
    ]
    provider = StaticMarketStateProvider(
        {
            "narrow": _market_state("narrow", bid=0.48, ask=0.52),
            "wide": _market_state("wide", bid=0.01, ask=0.99),
        }
    )

    sample = sample_quoteable_window(
        records,
        settings=Settings(),
        config=ShadowAConfig(cycle_minutes=5),
        provider=provider,
    )

    assert sample.fetched_market_states == 2
    assert sample.quoteable_count == 1
    assert sample.quoteable_ratio == 0.5
    assert sample.reason_counts["spread_too_wide"] == 1
    assert sample.reason_counts["spread_not_normalizable"] == 1


def test_summarize_quoteable_samples_builds_windows_and_hour_buckets() -> None:
    samples = [
        QuoteableWindowSample(
            sample_id="s1",
            sampled_at="2026-03-31T00:00:00Z",
            interval_minutes=5,
            selection_mode="broad",
            input_markets=2,
            strict_eligible_count=1,
            metadata_candidate_pool_count=2,
            metadata_fetch_limit=2,
            fetched_market_states=2,
            quoteable_count=1,
            quoteable_ratio=0.5,
            observations=[
                QuoteableMarketObservation(market_id="m1", title="M1", quoteable=True, best_normalized_spread_bps=700.0, best_top_depth_notional=12.0, best_top_depth_shares=20.0),
                QuoteableMarketObservation(market_id="m2", title="M2", quoteable=False, reasons=["spread_too_wide"]),
            ],
        ),
        QuoteableWindowSample(
            sample_id="s2",
            sampled_at="2026-03-31T00:05:00Z",
            interval_minutes=5,
            selection_mode="broad",
            input_markets=2,
            strict_eligible_count=1,
            metadata_candidate_pool_count=2,
            metadata_fetch_limit=2,
            fetched_market_states=2,
            quoteable_count=1,
            quoteable_ratio=0.5,
            observations=[
                QuoteableMarketObservation(market_id="m1", title="M1", quoteable=True, best_normalized_spread_bps=650.0, best_top_depth_notional=14.0, best_top_depth_shares=22.0),
                QuoteableMarketObservation(market_id="m2", title="M2", quoteable=False, reasons=["spread_too_wide"]),
            ],
        ),
        QuoteableWindowSample(
            sample_id="s3",
            sampled_at="2026-03-31T12:00:00Z",
            interval_minutes=5,
            selection_mode="broad",
            input_markets=2,
            strict_eligible_count=1,
            metadata_candidate_pool_count=2,
            metadata_fetch_limit=2,
            fetched_market_states=2,
            quoteable_count=1,
            quoteable_ratio=0.5,
            observations=[
                QuoteableMarketObservation(market_id="m2", title="M2", quoteable=True, best_normalized_spread_bps=500.0, best_top_depth_notional=20.0, best_top_depth_shares=35.0),
                QuoteableMarketObservation(market_id="m1", title="M1", quoteable=False, reasons=["spread_too_wide"]),
            ],
        ),
    ]

    summary = summarize_quoteable_samples(samples)

    assert summary.sample_count == 3
    assert summary.markets_seen == 2
    assert summary.markets_checked == 6
    assert summary.quoteable_count == 3
    assert summary.quoteable_minutes_by_market["m1"] == 10
    assert summary.quoteable_minutes_by_market["m2"] == 5
    assert summary.best_hours_utc[0]["hour_utc"] == 0
    assert summary.best_dayparts_utc[0]["daypart_utc"] == "00-05"
    assert len(summary.quoteable_windows) == 2
    assert summary.median_normalized_spread_bps_when_quoteable == 650.0
    assert summary.conclusion_hint == "narrow_subset_quoteable"


def test_run_quoteable_window_monitor_writes_artifacts(tmp_path) -> None:
    records = [_market_record("narrow", "Will BTC be above 120k on June 30?")]
    provider = StaticMarketStateProvider({"narrow": _market_state("narrow", bid=0.48, ask=0.52)})

    summary = run_quoteable_window_monitor(
        records,
        settings=Settings(),
        config=ShadowAConfig(cycle_minutes=5, discovery_max_candidates=10),
        provider=provider,
        samples_path=tmp_path / "samples.jsonl",
        summary_path=tmp_path / "latest.json",
        markdown_path=tmp_path / "latest.md",
        iterations=1,
        sleep_seconds=1,
    )

    assert summary.sample_count == 1
    assert (tmp_path / "samples.jsonl").exists()
    assert (tmp_path / "latest.json").exists()
    assert (tmp_path / "latest.md").exists()
