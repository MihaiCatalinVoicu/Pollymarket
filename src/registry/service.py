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


def _coerce_json_list(value: Any) -> list[Any]:
    if value in ("", None):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [value]
        return parsed if isinstance(parsed, list) else [parsed]
    return [value]


def _coerce_date(value: Any):
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def normalize_market(raw: dict[str, Any], event_lookup: dict[str, dict[str, Any]] | None = None) -> MarketRecord:
    rules_text = raw.get("rules") or raw.get("resolution_rules") or raw.get("description") or raw.get("resolutionSource") or ""
    reward_raw = raw.get("reward") or raw.get("reward_config") or raw.get("liquidityReward") or {}
    if not reward_raw and raw.get("clobRewards"):
        reward_raw = {
            "min_incentive_size": raw.get("rewardsMinSize"),
            "max_incentive_spread": raw.get("rewardsMaxSpread"),
            "reward_allocation": sum(_coerce_float(item.get("rewardsAmount") or item.get("rewardsDailyRate")) for item in raw.get("clobRewards", [])),
            "programs": raw.get("clobRewards"),
        }
    outcomes = _coerce_json_list(raw.get("outcomes") or raw.get("outcome_names") or raw.get("tokens"))
    token_ids_raw = _coerce_json_list(raw.get("tokenIds") or raw.get("clobTokenIds"))
    event_payload = raw.get("events") or []
    embedded_event = event_payload[0] if isinstance(event_payload, list) and event_payload and isinstance(event_payload[0], dict) else {}
    event_id = str(raw.get("eventId") or raw.get("event_id") or embedded_event.get("id") or "").strip() or None
    linked_event = dict((event_lookup or {}).get(event_id, {})) if event_id else {}
    primary_event = linked_event or embedded_event
    event_tags = primary_event.get("tags") or []
    derived_tags = [
        str(item.get("slug") or item.get("label") or "").strip()
        for item in event_tags
        if isinstance(item, dict) and str(item.get("slug") or item.get("label") or "").strip()
    ]
    allowed_categories = {"crypto", "finance", "tech", "economy", "economics"}
    derived_category = next((tag.lower() for tag in derived_tags if tag.lower() in allowed_categories), None)
    if outcomes and all(isinstance(item, dict) for item in outcomes):
        outcome_names = [str(item.get("name") or item.get("outcome") or "").strip() for item in outcomes]
        token_ids = [str(item.get("token_id") or item.get("tokenId") or item.get("asset_id") or "").strip() for item in outcomes]
    else:
        outcome_names = [str(item).strip() for item in outcomes]
        token_ids = [str(item).strip() for item in token_ids_raw]
    reward_config = RewardConfig(
        min_incentive_size=_coerce_float(reward_raw.get("min_incentive_size")),
        max_incentive_spread=_coerce_float(reward_raw.get("max_incentive_spread")),
        reward_allocation=_coerce_float(reward_raw.get("reward_allocation") or reward_raw.get("allocation")),
        raw=dict(reward_raw) if isinstance(reward_raw, dict) else {},
    )
    return MarketRecord(
        event_id=event_id,
        market_id=str(raw.get("id") or raw.get("marketId") or raw.get("market_id") or "").strip() or None,
        slug=str(raw.get("slug") or "").strip() or None,
        title=str(raw.get("question") or raw.get("title") or raw.get("name") or "unknown market").strip(),
        category=str(raw.get("category") or raw.get("group") or primary_event.get("category") or derived_category or "").strip() or None,
        tags=[tag for tag in derived_tags] or [str(item).strip() for item in _coerce_json_list(raw.get("tags")) if str(item).strip()],
        question_id=str(raw.get("questionId") or raw.get("question_id") or "").strip() or None,
        condition_id=str(raw.get("conditionId") or raw.get("condition_id") or "").strip() or None,
        token_ids=[item for item in token_ids if item],
        outcomes=[item for item in outcome_names if item],
        active=_coerce_bool(raw.get("active", not _coerce_bool(raw.get("closed")))),
        closed=_coerce_bool(raw.get("closed") or primary_event.get("closed")),
        resolved=_coerce_bool(raw.get("resolved")),
        enable_order_book=_coerce_bool(raw.get("enableOrderBook") or raw.get("enable_order_book") or primary_event.get("enableOrderBook")),
        fees_enabled=_coerce_bool(raw.get("feesEnabled") or raw.get("enableFees") or raw.get("feeEnabled") or raw.get("holdingRewardsEnabled") or bool(raw.get("clobRewards"))),
        neg_risk=_coerce_bool(raw.get("negRisk") or raw.get("neg_risk")),
        neg_risk_augmented=_coerce_bool(raw.get("negRiskAugmented") or raw.get("neg_risk_augmented")),
        open_interest=_coerce_float(raw.get("openInterest") or raw.get("open_interest") or primary_event.get("openInterest") or raw.get("liquidityClob") or raw.get("liquidity")),
        volume_24h=_coerce_float(raw.get("volume24hr") or raw.get("volume24h") or raw.get("volume24hrClob") or primary_event.get("volume24hr") or raw.get("volume")),
        tick_size=_coerce_float(raw.get("tickSize") or raw.get("minimum_tick_size") or raw.get("tick_size") or raw.get("orderPriceMinTickSize")) or None,
        end_date=_coerce_date(raw.get("endDate") or raw.get("end_date") or primary_event.get("endDate")),
        close_date=_coerce_date(raw.get("closeDate") or raw.get("close_date") or primary_event.get("endDate")),
        rules=RulesVersion(
            rules_text=str(rules_text),
            rules_hash=hash_rules(str(rules_text)),
            resolution_source=str(raw.get("resolutionSource") or raw.get("oracle") or primary_event.get("resolutionSource") or "").strip() or None,
        ),
        reward_config=reward_config,
        raw={**dict(raw), "__event": primary_event} if primary_event else dict(raw),
    )


def build_registry_snapshot(raw_markets: list[dict[str, Any]], raw_events: list[dict[str, Any]] | None = None) -> list[MarketRecord]:
    event_lookup = {
        str(item.get("id")): item
        for item in (raw_events or [])
        if isinstance(item, dict) and item.get("id") is not None
    }
    return [normalize_market(raw, event_lookup=event_lookup) for raw in raw_markets]


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
