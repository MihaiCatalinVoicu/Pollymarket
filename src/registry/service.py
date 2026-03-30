from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.registry.filtering import MarketEligibilityDecision, UniverseFilterPolicy, evaluate_market
from src.registry.models import MarketRecord, RewardConfig, RulesVersion, hash_rules


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def _coerce_float(value: Any) -> float:
    try:
        if value in ("", None):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _coerce_date(value: Any):
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def normalize_market(raw: dict[str, Any]) -> MarketRecord:
    rules_text = raw.get("rules") or raw.get("resolution_rules") or raw.get("description") or raw.get("resolutionSource") or ""
    reward_raw = raw.get("reward") or raw.get("reward_config") or raw.get("liquidityReward") or {}
    outcomes = raw.get("outcomes") or raw.get("outcome_names") or raw.get("tokens") or []
    if outcomes and all(isinstance(item, dict) for item in outcomes):
        outcome_names = [str(item.get("name") or item.get("outcome") or "").strip() for item in outcomes]
        token_ids = [str(item.get("token_id") or item.get("tokenId") or item.get("asset_id") or "").strip() for item in outcomes]
    else:
        outcome_names = [str(item).strip() for item in outcomes]
        token_ids = [str(item).strip() for item in raw.get("tokenIds", [])]
    reward_config = RewardConfig(
        min_incentive_size=_coerce_float(reward_raw.get("min_incentive_size")),
        max_incentive_spread=_coerce_float(reward_raw.get("max_incentive_spread")),
        reward_allocation=_coerce_float(reward_raw.get("reward_allocation") or reward_raw.get("allocation")),
        raw=dict(reward_raw) if isinstance(reward_raw, dict) else {},
    )
    return MarketRecord(
        event_id=str(raw.get("eventId") or raw.get("event_id") or "").strip() or None,
        market_id=str(raw.get("id") or raw.get("marketId") or raw.get("market_id") or "").strip() or None,
        slug=str(raw.get("slug") or "").strip() or None,
        title=str(raw.get("question") or raw.get("title") or raw.get("name") or "unknown market").strip(),
        category=str(raw.get("category") or raw.get("group") or "").strip() or None,
        tags=[str(item).strip() for item in raw.get("tags", []) if str(item).strip()],
        question_id=str(raw.get("questionId") or raw.get("question_id") or "").strip() or None,
        condition_id=str(raw.get("conditionId") or raw.get("condition_id") or "").strip() or None,
        token_ids=[item for item in token_ids if item],
        outcomes=[item for item in outcome_names if item],
        active=_coerce_bool(raw.get("active", not _coerce_bool(raw.get("closed")))),
        closed=_coerce_bool(raw.get("closed")),
        resolved=_coerce_bool(raw.get("resolved")),
        enable_order_book=_coerce_bool(raw.get("enableOrderBook") or raw.get("enable_order_book")),
        fees_enabled=_coerce_bool(raw.get("feesEnabled") or raw.get("enableFees") or raw.get("feeEnabled")),
        neg_risk=_coerce_bool(raw.get("negRisk") or raw.get("neg_risk")),
        neg_risk_augmented=_coerce_bool(raw.get("negRiskAugmented") or raw.get("neg_risk_augmented")),
        open_interest=_coerce_float(raw.get("openInterest") or raw.get("open_interest")),
        volume_24h=_coerce_float(raw.get("volume24hr") or raw.get("volume24h") or raw.get("volume")),
        tick_size=_coerce_float(raw.get("tickSize") or raw.get("minimum_tick_size") or raw.get("tick_size")) or None,
        end_date=_coerce_date(raw.get("endDate") or raw.get("end_date")),
        close_date=_coerce_date(raw.get("closeDate") or raw.get("close_date")),
        rules=RulesVersion(
            rules_text=str(rules_text),
            rules_hash=hash_rules(str(rules_text)),
            resolution_source=str(raw.get("resolutionSource") or raw.get("oracle") or "").strip() or None,
        ),
        reward_config=reward_config,
        raw=dict(raw),
    )


def build_registry_snapshot(raw_markets: list[dict[str, Any]]) -> list[MarketRecord]:
    return [normalize_market(raw) for raw in raw_markets]


def filter_registry(records: list[MarketRecord], policy: UniverseFilterPolicy, *, as_of: date) -> list[MarketEligibilityDecision]:
    return [evaluate_market(record, policy, as_of=as_of) for record in records]


def write_snapshot(path: str | Path, records: list[MarketRecord]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps([record.model_dump(mode="json") for record in records], indent=2), encoding="utf-8")
    return output


def write_eligibility(path: str | Path, decisions: list[MarketEligibilityDecision]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = [{"market_id": decision.market_id, "eligible": decision.eligible, "reasons": decision.reasons} for decision in decisions]
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output
