from __future__ import annotations

import json

from src.config import Settings
from src.registry.models import MarketRecord, RewardConfig, RulesVersion
from src.shadow import service as shadow_service
from src.shadow.service import ShadowAConfig, ShadowMarketState, StaticMarketStateProvider, TokenShadowState, run_shadow_a


def _market_record(*, market_id: str, title: str, open_interest: float, volume_24h: float, reward_allocation: float) -> MarketRecord:
    return MarketRecord(
        event_id=f"event-{market_id}",
        market_id=market_id,
        slug=market_id,
        title=title,
        category="crypto",
        tags=["crypto"],
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
        open_interest=open_interest,
        volume_24h=volume_24h,
        tick_size=0.01,
        rules=RulesVersion(
            rules_text="This market resolves to Yes if the objective event occurs by the listed deadline based on the named source.",
            rules_hash=f"hash-{market_id}",
            resolution_source="official",
        ),
        reward_config=RewardConfig(
            min_incentive_size=5.0,
            max_incentive_spread=80.0,
            reward_allocation=reward_allocation,
        ),
    )


def _market_state(*, market_id: str, title: str, bid: float, ask: float, open_interest: float, volume_24h: float, reward_allocation: float) -> ShadowMarketState:
    midpoint = round((bid + ask) / 2.0, 4)
    return ShadowMarketState(
        market_id=market_id,
        title=title,
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
            bid_size=21.0,
            ask_size=17.0,
            midpoint=round(1.0 - midpoint, 4),
            last_trade_price=round(1.0 - midpoint, 4),
        ),
        fee_rate_bps=2.0,
        reward_config=RewardConfig(
            min_incentive_size=5.0,
            max_incentive_spread=80.0,
            reward_allocation=reward_allocation,
        ),
        time_to_resolution_days=21.0,
        rules_ambiguity_score=0.02,
        open_interest=open_interest,
        volume_24h=volume_24h,
    )


def test_shadow_a_emits_required_metrics_and_paper_only_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(shadow_service, "SHADOW_ROOT", tmp_path / "shadow")
    monkeypatch.setattr(shadow_service, "RUN_MANIFEST_ROOT", tmp_path / "runtime" / "run_manifests")
    monkeypatch.setattr(shadow_service, "RUNTIME_ROOT", tmp_path / "runtime")
    monkeypatch.setattr(shadow_service, "emit_event", lambda *args, **kwargs: {})
    monkeypatch.setattr(shadow_service, "_load_inventory_validation_flag", lambda path=shadow_service.RUNTIME_ROOT / "venue_smoke.json": (True, []))

    record = _market_record(market_id="m1", title="BTC above 100k", open_interest=25_000.0, volume_24h=12_000.0, reward_allocation=144.0)
    state = _market_state(market_id="m1", title="BTC above 100k", bid=0.48, ask=0.52, open_interest=25_000.0, volume_24h=12_000.0, reward_allocation=144.0)
    report = run_shadow_a(
        [record],
        settings=Settings(),
        config=ShadowAConfig(shadow_days=1.0),
        provider=StaticMarketStateProvider({"m1": state}),
    )

    assert report.current_phase == "shadow_live"
    assert report.inventory_path_validated is True
    for key in (
        "quote_edge_net",
        "spread_capture_usdc",
        "reward_usdc",
        "rebate_usdc",
        "inventory_skew_pct",
        "full_set_parity_bps",
        "stale_take_pnl_usdc",
        "ws_desync_ms",
        "heartbeat_gap_ms",
        "reject_ratio",
        "cancel_ratio",
        "settlement_lag_minutes",
        "reconciliation_clean",
    ):
        assert key in report.metrics_summary

    assert report.market_results[0].latency_overlay["should_stale_take"] is False
    arming_payload = json.loads((tmp_path / "runtime" / "strategy_arming.json").read_text(encoding="utf-8"))
    verdict = arming_payload["polymarket"]["polymarket_mm_v1"]
    assert verdict["state"] == "PAPER_ONLY"
    assert "insufficient_shadow_days" in verdict["reasons"]


def test_shadow_a_selects_highest_scoring_markets_first(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(shadow_service, "SHADOW_ROOT", tmp_path / "shadow")
    monkeypatch.setattr(shadow_service, "RUN_MANIFEST_ROOT", tmp_path / "runtime" / "run_manifests")
    monkeypatch.setattr(shadow_service, "RUNTIME_ROOT", tmp_path / "runtime")
    monkeypatch.setattr(shadow_service, "emit_event", lambda *args, **kwargs: {})
    monkeypatch.setattr(shadow_service, "_load_inventory_validation_flag", lambda path=shadow_service.RUNTIME_ROOT / "venue_smoke.json": (True, []))

    strong_record = _market_record(market_id="strong", title="ETH above 5k", open_interest=40_000.0, volume_24h=20_000.0, reward_allocation=200.0)
    weak_record = _market_record(market_id="weak", title="SOL above 500", open_interest=500.0, volume_24h=200.0, reward_allocation=0.0)
    provider = StaticMarketStateProvider(
        {
            "strong": _market_state(market_id="strong", title="ETH above 5k", bid=0.47, ask=0.51, open_interest=40_000.0, volume_24h=20_000.0, reward_allocation=200.0),
            "weak": _market_state(market_id="weak", title="SOL above 500", bid=0.40, ask=0.60, open_interest=500.0, volume_24h=200.0, reward_allocation=0.0),
        }
    )

    report = run_shadow_a(
        [weak_record, strong_record],
        settings=Settings(),
        config=ShadowAConfig(max_markets=1, shadow_days=1.0),
        provider=provider,
    )

    assert report.selected_market_ids == ["strong"]
    assert len(report.market_results) == 1


def test_shadow_a_prefers_diverse_events_before_second_market_from_same_cluster(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(shadow_service, "SHADOW_ROOT", tmp_path / "shadow")
    monkeypatch.setattr(shadow_service, "RUN_MANIFEST_ROOT", tmp_path / "runtime" / "run_manifests")
    monkeypatch.setattr(shadow_service, "RUNTIME_ROOT", tmp_path / "runtime")
    monkeypatch.setattr(shadow_service, "emit_event", lambda *args, **kwargs: {})
    monkeypatch.setattr(shadow_service, "_load_inventory_validation_flag", lambda path=shadow_service.RUNTIME_ROOT / "venue_smoke.json": (True, []))

    same_event_a = _market_record(market_id="a", title="MegaETH FDV > 2B", open_interest=50_000.0, volume_24h=20_000.0, reward_allocation=200.0)
    same_event_b = _market_record(market_id="b", title="MegaETH FDV > 6B", open_interest=49_000.0, volume_24h=19_500.0, reward_allocation=195.0)
    other_event = _market_record(market_id="c", title="OpenAI hardware by June 30", open_interest=35_000.0, volume_24h=15_000.0, reward_allocation=150.0)
    same_event_a.event_id = "megaeth-event"
    same_event_b.event_id = "megaeth-event"
    other_event.event_id = "openai-event"
    same_event_a.tags = ["crypto", "megaeth"]
    same_event_b.tags = ["crypto", "megaeth"]
    other_event.category = "tech"
    other_event.tags = ["tech", "openai"]

    provider = StaticMarketStateProvider(
        {
            "a": _market_state(market_id="a", title="MegaETH FDV > 2B", bid=0.48, ask=0.52, open_interest=50_000.0, volume_24h=20_000.0, reward_allocation=200.0),
            "b": _market_state(market_id="b", title="MegaETH FDV > 6B", bid=0.47, ask=0.51, open_interest=49_000.0, volume_24h=19_500.0, reward_allocation=195.0),
            "c": ShadowMarketState(
                market_id="c",
                title="OpenAI hardware by June 30",
                category="tech",
                event_id="openai-event",
                tick_size=0.01,
                primary=TokenShadowState(
                    token_id="c-yes",
                    outcome="Yes",
                    best_bid=0.46,
                    best_ask=0.5,
                    bid_size=25.0,
                    ask_size=24.0,
                    midpoint=0.48,
                    last_trade_price=0.48,
                ),
                complementary=TokenShadowState(
                    token_id="c-no",
                    outcome="No",
                    best_bid=0.5,
                    best_ask=0.54,
                    bid_size=26.0,
                    ask_size=22.0,
                    midpoint=0.52,
                    last_trade_price=0.52,
                ),
                fee_rate_bps=2.0,
                reward_config=RewardConfig(
                    min_incentive_size=5.0,
                    max_incentive_spread=80.0,
                    reward_allocation=150.0,
                ),
                time_to_resolution_days=30.0,
                rules_ambiguity_score=0.02,
                open_interest=35_000.0,
                volume_24h=15_000.0,
            ),
        }
    )

    report = run_shadow_a(
        [same_event_a, same_event_b, other_event],
        settings=Settings(),
        config=ShadowAConfig(max_markets=2, shadow_days=1.0),
        provider=provider,
    )

    assert report.selected_market_ids[0] == "a"
    assert report.selected_market_ids[1] == "c"
