from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.ops.promotion_policy import promotion_blocker_classes, promotion_verdict
from src.ops.run_manifest import build_promotion_decision_manifest, manifest_artifact_link, write_run_manifest


def _num(metrics: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(metrics.get(key, default))
    except (TypeError, ValueError):
        return default


def load_promotion_cfg(path: str | Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def evaluate_polymarket_promotion(metrics: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    promotion = (((cfg.get("polymarket") or {}).get("promotion")) or {})
    reasons: list[str] = []
    current_phase = str(metrics.get("current_phase") or "shadow_live")
    if not bool(metrics.get("inventory_path_validated", False)):
        reasons.append("inventory_path_unvalidated")
    if not bool(metrics.get("reconciliation_clean", True)):
        reasons.append("reconciliation_not_clean")
    if not bool(metrics.get("heartbeat_healthy", True)):
        reasons.append("heartbeat_unhealthy")
    if not bool(metrics.get("geoblock_ok", True)):
        reasons.append("geoblock_failed")
    if bool(metrics.get("auth_invalid", False)) or not bool(metrics.get("auth_ok", True)):
        reasons.append("auth_invalid")
    if bool(metrics.get("hard_kill", False)):
        reasons.append("hard_risk_governor_failure")
    if (
        _num(metrics, "spread_capture_usdc") <= 0.0
        and _num(metrics, "reward_usdc") <= 0.0
        and _num(metrics, "rebate_usdc") <= 0.0
    ):
        reasons.append("no_participation")
    if _num(metrics, "quote_edge_net") < _num(promotion, "min_quote_edge_net_usdc", 0.0):
        reasons.append("negative_quote_edge")
    if _num(metrics, "spread_capture_usdc") < _num(promotion, "min_spread_capture_usdc", 0.0):
        reasons.append("negative_spread_capture")
    if _num(metrics, "net_edge_ex_rewards_usdc") < _num(promotion, "min_net_edge_ex_rewards_usdc", 0.0):
        reasons.append("rewards_only_pnl")
    if _num(metrics, "market_concentration_pct") > _num(promotion, "max_market_concentration_pct", 0.4):
        reasons.append("market_concentration_high")
    if current_phase in {"paper", "shadow_live"} and _num(metrics, "shadow_days") < _num(promotion, "min_shadow_days", 21):
        reasons.append("insufficient_shadow_days")
    if current_phase in {"micro_live", "REAL_MICRO_ACTIVE"} and _num(metrics, "micro_live_days") < _num(promotion, "min_micro_live_days", 30):
        reasons.append("insufficient_micro_live_days")
    hard_disarm_reasons = {"heartbeat_unhealthy", "geoblock_failed", "auth_invalid", "hard_risk_governor_failure"}
    if current_phase in {"micro_live", "REAL_MICRO_ACTIVE", "ARMED_REAL_MICRO"} and any(
        reason in hard_disarm_reasons for reason in reasons
    ):
        state = "AUTO_DISARMED"
    elif current_phase in {"micro_live", "REAL_MICRO_ACTIVE"} and not reasons:
        state = "REAL_MICRO_ACTIVE"
    elif not reasons:
        state = "ARMED_REAL_MICRO"
    else:
        state = "PAPER_ONLY"
    blocker_classes = promotion_blocker_classes(reasons)
    return {
        "state": state,
        "reasons": reasons,
        "promotion_verdict": promotion_verdict(eligible_for_arming=state in {"ARMED_REAL_MICRO", "REAL_MICRO_ACTIVE"} and not reasons, blocker_classes=blocker_classes, state_after=state),
        "promotion_blocker_classes": blocker_classes,
    }


def evaluate_strategy_state(strategy_key: str, venue: str, metrics: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    if venue != "polymarket":
        raise ValueError("unsupported venue")
    verdict = evaluate_polymarket_promotion(metrics, cfg)
    return {
        "strategy_key": strategy_key,
        "venue": venue,
        "state": verdict["state"],
        "reasons": verdict["reasons"],
        "promotion_verdict": verdict["promotion_verdict"],
        "promotion_blocker_classes": verdict["promotion_blocker_classes"],
        "metrics_snapshot": {**dict(metrics or {}), "promotion_verdict": verdict["promotion_verdict"], "promotion_blocker_classes": verdict["promotion_blocker_classes"]},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def write_strategy_arming(path: str | Path, payload: dict[str, Any]) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def emit_promotion_manifest(path: str | Path, payload: dict[str, Any]) -> Path:
    current = (payload.get("polymarket") or {}).get("polymarket_mm_v1") or {}
    completed_at = str(current.get("updated_at") or datetime.now(timezone.utc).isoformat())
    manifest = build_promotion_decision_manifest(
        source_run_id=f"polymarket:polymarket_mm_v1:promotion:{completed_at}",
        strategy_id="polymarket_mm_v1",
        family_id="polymarket_mm_v1",
        state_before=str(current.get("state_before") or "PAPER_ONLY"),
        state_after=str(current.get("state") or "PAPER_ONLY"),
        hard_blockers=list(current.get("reasons") or []),
        metrics_snapshot=dict(current.get("metrics_snapshot") or {}),
        artifact_links=[manifest_artifact_link(path, "strategy_arming_json")],
        completed_at=completed_at,
    )
    return write_run_manifest(path, manifest)
