from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.ops.promotion_policy import promotion_blocker_classes, promotion_verdict
from src.ops.runtime_event_logger import RunContext


OPERATIONAL_LABELS = {"promote_ready", "expand_oos", "fix_now", "frozen", "degraded", "pipeline_broken", "parity_fail", "data_missing"}
EVALUATION_PHASES = {"research", "paper", "shadow_live", "promotion_review", "disarm_review", "live"}
MANIFEST_BLOCK_KEYS = {"market_regime", "blockers", "execution_summary", "risk_layers", "promotion_behavior"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalized_string_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        return [values] if values.strip() else []
    if not isinstance(values, (list, tuple, set)):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _coerce_float(value: Any) -> float | None:
    try:
        if value in ("", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_manifest_blocks(metrics_summary: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    normalized = dict(metrics_summary or {})
    extracted: dict[str, dict[str, Any]] = {}
    for key in MANIFEST_BLOCK_KEYS:
        raw = normalized.pop(key, None)
        if isinstance(raw, dict) and raw:
            extracted[key] = dict(raw)
    return normalized, extracted


def _merge_optional_block(derived: dict[str, Any] | None, provided: dict[str, Any] | None) -> dict[str, Any] | None:
    base = dict(derived or {})
    incoming = dict(provided or {})
    for key, value in incoming.items():
        if value is None:
            continue
        if isinstance(value, dict) and not value:
            continue
        if isinstance(value, list) and not value:
            continue
        base[key] = value
    return base or None


def _derive_market_regime(metrics: dict[str, Any]) -> dict[str, Any]:
    permission = "BLOCKED" if not metrics.get("geoblock_ok", True) or not metrics.get("auth_ok", True) else "NORMAL"
    if metrics.get("risk_blocked"):
        permission = "REDUCED"
    quote_edge = _coerce_float(metrics.get("quote_edge_net")) or 0.0
    trend_state = "FAVORABLE" if quote_edge > 0.05 else ("NEUTRAL" if quote_edge >= 0.0 else "UNFAVORABLE")
    ambiguity = _coerce_float(metrics.get("rules_ambiguity_score")) or 0.0
    risk_state = "TOXIC" if ambiguity >= 0.20 else ("ELEVATED" if ambiguity > 0 else "SAFE")
    reasons = _normalized_string_list(metrics.get("blocked_by"))
    return {
        "permission": permission,
        "risk_state": risk_state,
        "trend_state": trend_state,
        "vol_state": "EXPANDING" if (metrics.get("ws_desync_ms") or 0) > 500 else "CALM",
        "size_multiplier": _coerce_float(metrics.get("size_multiplier")) or 1.0,
        "reasons": reasons,
        "signature": f"{permission}|{risk_state}|{trend_state}",
    }


def _derive_blockers(metrics: dict[str, Any]) -> dict[str, Any]:
    raw = _normalized_string_list(metrics.get("blocked_by")) + _normalized_string_list(metrics.get("hard_blockers"))
    classes: list[str] = []
    for blocker in raw:
        lowered = blocker.lower()
        if "parity" in lowered:
            classes.append("PARITY_BLOCK")
        elif lowered in {"market_notional_limit", "event_notional_limit", "category_notional_limit"}:
            classes.append("CAPACITY_LIMIT")
        elif lowered in {"heartbeat_failure", "auth_invalid", "geoblock_failure"}:
            classes.append("EXECUTION_DEGRADATION")
        elif lowered.startswith("missing_"):
            classes.append("PROMOTION_BLOCK")
        else:
            classes.append("RISK_REDUCTION")
    classes = list(dict.fromkeys(classes))
    return {"classes": classes, "raw": raw, "dominant_class": classes[0] if classes else None}


def _derive_execution_summary(metrics: dict[str, Any]) -> dict[str, Any]:
    reject_ratio = _coerce_float(metrics.get("reject_ratio")) or 0.0
    cancel_ratio = _coerce_float(metrics.get("cancel_ratio")) or 0.0
    if reject_ratio > 0.10 or cancel_ratio > 0.80:
        fill_quality = "BAD"
    elif reject_ratio > 0.03 or cancel_ratio > 0.50:
        fill_quality = "DEGRADED"
    else:
        fill_quality = "GOOD"
    return {
        "fill_quality": fill_quality,
        "slippage_band": "LOW",
        "mode_distribution": dict(metrics.get("mode_distribution") or {}),
        "slippage_bps_avg": _coerce_float(metrics.get("slippage_bps_avg")) or 0.0,
        "fallback_rate": _coerce_float(metrics.get("fallback_rate")) or 0.0,
        "abort_rate": _coerce_float(metrics.get("abort_rate")) or 0.0,
        "policy_blocked": bool(metrics.get("execution_policy_blocked", False)),
        "blocker_classes": _normalized_string_list(metrics.get("execution_blocker_classes")),
    }


def _derive_risk_layers(metrics: dict[str, Any], market_regime: dict[str, Any], execution_summary: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "regime": {"status": "OK" if market_regime.get("permission") == "NORMAL" else "REDUCE", "events": market_regime.get("reasons", [])},
        "execution": {
            "status": "HALT" if execution_summary.get("policy_blocked") else ("DEGRADED" if execution_summary.get("fill_quality") != "GOOD" else "OK"),
            "events": execution_summary.get("blocker_classes", []),
        },
    }
    if metrics.get("hard_kill"):
        payload["global"] = {"status": "DISARM", "events": _normalized_string_list(metrics.get("hard_blockers"))}
    return payload


def _derive_promotion_behavior(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "regime_coverage": dict(metrics.get("regime_coverage") or {}),
        "performance_by_regime": dict(metrics.get("performance_by_regime") or {}),
        "block_rate": _coerce_float(metrics.get("block_rate")) or 0.0,
        "opportunity_efficiency": _coerce_float(metrics.get("opportunity_efficiency")) or 0.0,
        "block_quality": _coerce_float(metrics.get("block_quality")) or 0.0,
        "execution_consistency": _coerce_float(metrics.get("execution_consistency")) or 0.0,
        "parity_by_regime": dict(metrics.get("parity_by_regime") or {}),
        "regime_dependency": metrics.get("regime_dependency"),
    }


def default_policy_bundle(strategy_id: str) -> dict[str, Any]:
    return {
        "version": 1,
        "signal_policy_id": strategy_id,
        "risk_policy_id": "inventory_risk_governor_v1",
        "promotion_policy_id": "micro_live_validation_v1",
        "execution_policy_id": "post_only_quote_router_v1",
        "disarm_policy_id": "ops_fail_closed_v1",
    }


def manifest_artifact_link(path: str | Path, artifact_type: str = "run_manifest_v1") -> dict[str, Any]:
    return {"artifact_type": artifact_type, "path": str(Path(path))}


def canonical_family_id(strategy_id: str, family_id: str | None = None) -> str:
    return family_id or strategy_id or "polymarket_mm_v1"


def build_run_manifest(*, source_run_id: str, strategy_id: str, family_id: str | None = None, variant_id: str = "reward_aware_passive_v1", run_type: str, evaluation_phase: str, status: str, outcome_hint: str, metrics_summary: dict[str, Any] | None = None, artifact_links: list[dict[str, Any]] | None = None, next_phase_hint: str | None = None, parity_flags: list[str] | None = None, requires_action: bool = False, policy_bundle: dict[str, Any] | None = None, started_at: str | None = None, completed_at: str | None = None) -> dict[str, Any]:
    if evaluation_phase not in EVALUATION_PHASES:
        raise ValueError(f"unsupported evaluation_phase: {evaluation_phase}")
    if outcome_hint not in OPERATIONAL_LABELS:
        raise ValueError(f"unsupported outcome_hint: {outcome_hint}")
    normalized_metrics, provided_blocks = _extract_manifest_blocks(metrics_summary or {})
    market_regime = _merge_optional_block(_derive_market_regime(normalized_metrics), provided_blocks.get("market_regime"))
    blockers = _merge_optional_block(_derive_blockers(normalized_metrics), provided_blocks.get("blockers"))
    execution_summary = _merge_optional_block(_derive_execution_summary(normalized_metrics), provided_blocks.get("execution_summary"))
    risk_layers = _merge_optional_block(_derive_risk_layers(normalized_metrics, market_regime or {}, execution_summary or {}), provided_blocks.get("risk_layers"))
    promotion_behavior = _merge_optional_block(_derive_promotion_behavior(normalized_metrics), provided_blocks.get("promotion_behavior"))
    return {
        "manifest_version": 1,
        "source_repo": "polymarket-bot",
        "source_run_id": source_run_id,
        "strategy_id": strategy_id,
        "family_id": canonical_family_id(strategy_id, family_id),
        "variant_id": variant_id,
        "policy_bundle": dict(policy_bundle or default_policy_bundle(strategy_id)),
        "run_type": run_type,
        "evaluation_phase": evaluation_phase,
        "status": status,
        "started_at": started_at or _utc_now(),
        "completed_at": completed_at,
        "metrics_summary": normalized_metrics,
        "artifact_links": list(artifact_links or []),
        "market_regime": market_regime,
        "blockers": blockers,
        "execution_summary": execution_summary,
        "risk_layers": risk_layers,
        "promotion_behavior": promotion_behavior,
        "outcome_hint": outcome_hint,
        "next_phase_hint": next_phase_hint,
        "parity_flags": list(parity_flags or []),
        "requires_action": requires_action,
    }


def build_run_manifest_from_context(context: RunContext, *, run_type: str, evaluation_phase: str, status: str, outcome_hint: str, metrics_summary: dict[str, Any] | None = None, artifact_links: list[dict[str, Any]] | None = None, next_phase_hint: str | None = None, parity_flags: list[str] | None = None, requires_action: bool = False, policy_bundle: dict[str, Any] | None = None, started_at: str | None = None, completed_at: str | None = None) -> dict[str, Any]:
    return build_run_manifest(
        source_run_id=context.run_id,
        strategy_id=context.strategy_id,
        family_id=context.family,
        variant_id=context.variant_id or "reward_aware_passive_v1",
        run_type=run_type,
        evaluation_phase=evaluation_phase,
        status=status,
        outcome_hint=outcome_hint,
        metrics_summary=metrics_summary,
        artifact_links=artifact_links,
        next_phase_hint=next_phase_hint,
        parity_flags=parity_flags,
        requires_action=requires_action,
        policy_bundle=policy_bundle,
        started_at=started_at,
        completed_at=completed_at,
    )


def build_run_completed_manifest(context: RunContext, *, run_type: str, evaluation_phase: str, outcome_hint: str, metrics_summary: dict[str, Any] | None = None, artifact_links: list[dict[str, Any]] | None = None, next_phase_hint: str | None = None, parity_flags: list[str] | None = None, requires_action: bool = False, policy_bundle: dict[str, Any] | None = None, started_at: str | None = None, completed_at: str | None = None) -> dict[str, Any]:
    return build_run_manifest_from_context(context, run_type=run_type, evaluation_phase=evaluation_phase, status="completed", outcome_hint=outcome_hint, metrics_summary=metrics_summary, artifact_links=artifact_links, next_phase_hint=next_phase_hint, parity_flags=parity_flags, requires_action=requires_action, policy_bundle=policy_bundle, started_at=started_at, completed_at=completed_at)


def build_promotion_decision_manifest(*, source_run_id: str, strategy_id: str, state_before: str, state_after: str, hard_blockers: list[str] | None = None, metrics_snapshot: dict[str, Any] | None = None, family_id: str | None = None, variant_id: str = "reward_aware_passive_v1", artifact_links: list[dict[str, Any]] | None = None, policy_bundle: dict[str, Any] | None = None, started_at: str | None = None, completed_at: str | None = None) -> dict[str, Any]:
    blockers = list(hard_blockers or [])
    blocker_classes = promotion_blocker_classes(blockers)
    verdict = promotion_verdict(eligible_for_arming=state_after == "ARMED_REAL_MICRO" and not blockers, blocker_classes=blocker_classes, state_after=state_after)
    if state_after in {"ARMED_REAL_MICRO", "REAL_MICRO_ACTIVE"} and not blockers:
        outcome_hint = "promote_ready"
        next_phase_hint = "shadow_live"
        requires_action = False
    elif any(reason.startswith("missing_") for reason in blockers):
        outcome_hint = "data_missing"
        next_phase_hint = "research"
        requires_action = True
    elif any("parity" in reason for reason in blockers):
        outcome_hint = "parity_fail"
        next_phase_hint = "paper"
        requires_action = True
    else:
        outcome_hint = "expand_oos"
        next_phase_hint = "paper"
        requires_action = bool(blockers)
    metrics_payload = dict(metrics_snapshot or {})
    metrics_payload.update({"state_before": state_before, "state_after": state_after, "promotion_verdict": verdict, "promotion_blocker_classes": blocker_classes, "hard_blockers": blockers})
    return build_run_manifest(source_run_id=source_run_id, strategy_id=strategy_id, family_id=family_id, variant_id=variant_id, run_type="promotion_review", evaluation_phase="promotion_review", status="completed", outcome_hint=outcome_hint, metrics_summary=metrics_payload, artifact_links=artifact_links, next_phase_hint=next_phase_hint, requires_action=requires_action, policy_bundle=policy_bundle, started_at=started_at, completed_at=completed_at)


def write_run_manifest(path: str | Path, manifest: dict[str, Any]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
    return output
