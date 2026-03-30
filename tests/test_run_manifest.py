from __future__ import annotations

from src.ops.run_manifest import build_run_manifest


def test_run_manifest_uses_polymarket_contract_defaults() -> None:
    manifest = build_run_manifest(
        source_run_id="pm-shadow-001",
        strategy_id="polymarket_mm_v1",
        run_type="runtime_review",
        evaluation_phase="shadow_live",
        status="completed",
        outcome_hint="expand_oos",
        metrics_summary={
            "quote_edge_net": 1.2,
            "spread_capture_usdc": 2.5,
            "reward_usdc": 0.8,
            "rebate_usdc": 0.2,
            "inventory_skew_pct": 0.1,
            "full_set_parity_bps": 12,
            "stale_take_pnl_usdc": 0.1,
            "ws_desync_ms": 100,
            "heartbeat_gap_ms": 4000,
            "reject_ratio": 0.01,
            "cancel_ratio": 0.2,
            "settlement_lag_minutes": 0.0,
            "reconciliation_clean": True,
            "geoblock_ok": True,
            "auth_ok": True,
        },
    )
    assert manifest["source_repo"] == "polymarket-bot"
    assert manifest["family_id"] == "polymarket_mm_v1"
    assert manifest["policy_bundle"]["execution_policy_id"] == "post_only_quote_router_v1"
    assert manifest["market_regime"]["permission"] == "NORMAL"
    assert manifest["execution_summary"]["fill_quality"] == "GOOD"

