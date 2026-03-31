from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re

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
    blocked_tag_substrings: tuple[str, ...]
    penalized_tag_weights: dict[str, float]
    category_inference_keywords: dict[str, tuple[str, ...]]
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
            blocked_tag_substrings=tuple(str(value).lower() for value in deny.get("blocked_tag_substrings", [])),
            penalized_tag_weights={
                str(fragment).lower(): float(weight)
                for fragment, weight in (deny.get("penalized_tag_weights") or {}).items()
            },
            category_inference_keywords={
                str(category).lower(): tuple(str(keyword).lower() for keyword in keywords or [])
                for category, keywords in (allow.get("category_inference_keywords") or {}).items()
            },
            blocked_market_types={str(value).lower() for value in deny.get("blocked_market_types", [])},
        )


@dataclass
class MarketEligibilityDecision:
    market_id: str | None
    eligible: bool
    reasons: list[str]


def tag_penalty(record: MarketRecord, policy: UniverseFilterPolicy) -> float:
    penalty = 0.0
    tags = [tag.lower() for tag in record.tags]
    for fragment, weight in policy.penalized_tag_weights.items():
        if any(fragment in tag for tag in tags):
            penalty += float(weight)
    return min(penalty, 0.60)


def infer_market_category(record: MarketRecord, policy: UniverseFilterPolicy) -> str:
    explicit = (record.category or "").lower().strip()
    if explicit in policy.allowed_categories or explicit in policy.blocked_categories:
        return explicit
    raw_haystack = " ".join(
        part
        for part in [
            record.title,
            record.slug or "",
            " ".join(record.tags),
        ]
        if part
    ).lower()
    normalized_haystack = re.sub(r"[^a-z0-9]+", " ", raw_haystack).strip()
    tokens = normalized_haystack.split()
    token_set = set(tokens)

    def has_token_sequence(sequence: list[str]) -> bool:
        if not sequence or len(sequence) > len(tokens):
            return False
        window = len(sequence)
        return any(tokens[index : index + window] == sequence for index in range(0, len(tokens) - window + 1))

    for category, keywords in policy.category_inference_keywords.items():
        for keyword in keywords:
            normalized_keyword = re.sub(r"[^a-z0-9]+", " ", keyword.lower()).strip()
            if not normalized_keyword:
                continue
            keyword_tokens = normalized_keyword.split()
            if len(keyword_tokens) == 1:
                token = keyword_tokens[0]
                if token in token_set:
                    return category
            elif has_token_sequence(keyword_tokens):
                return category
    return explicit


def evaluate_market(record: MarketRecord, policy: UniverseFilterPolicy, *, as_of: date) -> MarketEligibilityDecision:
    reasons: list[str] = []
    category = infer_market_category(record, policy)
    title = record.title.lower()
    slug = (record.slug or "").lower()
    tags = [tag.lower() for tag in record.tags]

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
    if any(fragment in tag for fragment in policy.blocked_tag_substrings for tag in tags):
        reasons.append("tag_blocked")
    if not record.active or record.closed or record.resolved:
        reasons.append("market_not_live")
    return MarketEligibilityDecision(record.market_id, not reasons, reasons)
