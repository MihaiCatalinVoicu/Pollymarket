from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import yaml

from src.registry.models import MarketRecord


@dataclass
class UniverseFilterPolicy:
    allowed_categories: set[str]
    blocked_categories: set[str]
    require_orderbook_enabled: bool
    require_fees_enabled: bool
    require_clear_rules: bool
    require_named_outcomes_only: bool
    require_binary_outcomes: bool
    min_open_interest: float
    min_volume_24h: float
    max_days_to_resolution: int
    blocked_title_substrings: tuple[str, ...]
    blocked_slug_substrings: tuple[str, ...]
    blocked_market_types: set[str]

    @classmethod
    def from_yaml(cls, allowlist_path: str, denylist_path: str) -> "UniverseFilterPolicy":
        with open(allowlist_path, "r", encoding="utf-8") as handle:
            allow = yaml.safe_load(handle) or {}
        with open(denylist_path, "r", encoding="utf-8") as handle:
            deny = yaml.safe_load(handle) or {}
        return cls(
            allowed_categories={str(value).lower() for value in allow.get("allowed_categories", [])},
            blocked_categories={str(value).lower() for value in deny.get("blocked_categories", [])},
            require_orderbook_enabled=bool(allow.get("require_orderbook_enabled", True)),
            require_fees_enabled=bool(allow.get("require_fees_enabled", True)),
            require_clear_rules=bool(allow.get("require_clear_rules", True)),
            require_named_outcomes_only=bool(allow.get("require_named_outcomes_only", True)),
            require_binary_outcomes=bool(allow.get("require_binary_outcomes", True)),
            min_open_interest=float(allow.get("min_open_interest", 0.0)),
            min_volume_24h=float(allow.get("min_volume_24h", 0.0)),
            max_days_to_resolution=int(allow.get("max_days_to_resolution", 365)),
            blocked_title_substrings=tuple(str(value).lower() for value in allow.get("blocked_title_substrings", [])),
            blocked_slug_substrings=tuple(str(value).lower() for value in deny.get("blocked_slug_substrings", [])),
            blocked_market_types={str(value).lower() for value in deny.get("blocked_market_types", [])},
        )


@dataclass
class MarketEligibilityDecision:
    market_id: str | None
    eligible: bool
    reasons: list[str]


def evaluate_market(record: MarketRecord, policy: UniverseFilterPolicy, *, as_of: date) -> MarketEligibilityDecision:
    reasons: list[str] = []
    category = (record.category or "").lower()
    title = record.title.lower()
    slug = (record.slug or "").lower()

    if category not in policy.allowed_categories:
        reasons.append("category_not_allowlisted")
    if category in policy.blocked_categories:
        reasons.append("category_blocked")
    if policy.require_orderbook_enabled and not record.enable_order_book:
        reasons.append("orderbook_disabled")
    if policy.require_fees_enabled and not record.fees_enabled:
        reasons.append("fees_disabled")
    if policy.require_binary_outcomes and not record.is_binary:
        reasons.append("non_binary_market")
    if policy.require_named_outcomes_only and record.has_placeholder_outcome:
        reasons.append("placeholder_or_other_outcome")
    if record.neg_risk_augmented:
        reasons.append("neg_risk_augmented_blocked")
    if policy.require_clear_rules and len(record.rules.rules_text.strip()) < 40:
        reasons.append("rules_not_clear")
    if record.open_interest < policy.min_open_interest:
        reasons.append("open_interest_too_low")
    if record.volume_24h < policy.min_volume_24h:
        reasons.append("volume_too_low")
    days_to_resolution = record.days_to_resolution(as_of)
    if days_to_resolution is None:
        reasons.append("missing_resolution_date")
    elif days_to_resolution < 0:
        reasons.append("already_expired")
    elif days_to_resolution > policy.max_days_to_resolution:
        reasons.append("resolution_too_far")
    if any(fragment in title for fragment in policy.blocked_title_substrings):
        reasons.append("title_blocked")
    if any(fragment in slug for fragment in policy.blocked_slug_substrings):
        reasons.append("slug_blocked")
    if not record.active or record.closed or record.resolved:
        reasons.append("market_not_live")
    return MarketEligibilityDecision(record.market_id, not reasons, reasons)

