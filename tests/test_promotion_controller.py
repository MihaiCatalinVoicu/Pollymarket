from __future__ import annotations

from src.ops.promotion_controller import evaluate_polymarket_promotion


def test_promotion_gate_stays_below_micro_live_when_inventory_path_is_unvalidated() -> None:
    verdict = evaluate_polymarket_promotion(
        {
            "current_phase": "shadow_live",
            "reconciliation_clean": True,
            "inventory_path_validated": False,
            "heartbeat_healthy": True,
            "geoblock_ok": True,
            "auth_ok": True,
            "quote_edge_net": 1.0,
            "spread_capture_usdc": 2.0,
            "net_edge_ex_rewards_usdc": 1.0,
            "market_concentration_pct": 0.2,
            "shadow_days": 30,
        },
        {"polymarket": {"promotion": {}}},
    )

    assert verdict["state"] == "PAPER_ONLY"
    assert "inventory_path_unvalidated" in verdict["reasons"]
    assert verdict["promotion_verdict"] == "REJECT"


def test_micro_live_hard_safety_failure_auto_disarms() -> None:
    verdict = evaluate_polymarket_promotion(
        {
            "current_phase": "REAL_MICRO_ACTIVE",
            "reconciliation_clean": True,
            "inventory_path_validated": True,
            "heartbeat_healthy": False,
            "geoblock_ok": True,
            "auth_ok": True,
            "quote_edge_net": 1.0,
            "spread_capture_usdc": 2.0,
            "net_edge_ex_rewards_usdc": 1.0,
            "market_concentration_pct": 0.2,
            "micro_live_days": 35,
        },
        {"polymarket": {"promotion": {}}},
    )

    assert verdict["state"] == "AUTO_DISARMED"
    assert "heartbeat_unhealthy" in verdict["reasons"]
    assert verdict["promotion_verdict"] == "DISARM"


def test_zero_participation_cannot_promote_even_if_other_metrics_are_neutral() -> None:
    verdict = evaluate_polymarket_promotion(
        {
            "current_phase": "shadow_live",
            "reconciliation_clean": True,
            "inventory_path_validated": True,
            "heartbeat_healthy": True,
            "geoblock_ok": True,
            "auth_ok": True,
            "quote_edge_net": 0.0,
            "spread_capture_usdc": 0.0,
            "reward_usdc": 0.0,
            "rebate_usdc": 0.0,
            "net_edge_ex_rewards_usdc": 0.0,
            "market_concentration_pct": 0.0,
            "shadow_days": 30,
        },
        {"polymarket": {"promotion": {}}},
    )

    assert verdict["state"] == "PAPER_ONLY"
    assert "no_participation" in verdict["reasons"]
    assert verdict["promotion_verdict"] == "PAPER_ONLY"
    assert "performance" in verdict["promotion_blocker_classes"]
