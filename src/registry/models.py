from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class RewardConfig(BaseModel):
    min_incentive_size: float | None = None
    max_incentive_spread: float | None = None
    reward_allocation: float | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class RulesVersion(BaseModel):
    rules_text: str
    rules_hash: str
    resolution_source: str | None = None


class MarketRecord(BaseModel):
    event_id: str | None = None
    market_id: str | None = None
    slug: str | None = None
    title: str
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    question_id: str | None = None
    condition_id: str | None = None
    token_ids: list[str] = Field(default_factory=list)
    outcomes: list[str] = Field(default_factory=list)
    active: bool = False
    closed: bool = False
    resolved: bool = False
    enable_order_book: bool = False
    fees_enabled: bool = False
    neg_risk: bool = False
    neg_risk_augmented: bool = False
    open_interest: float = 0.0
    volume_24h: float = 0.0
    tick_size: float | None = None
    end_date: date | None = None
    close_date: date | None = None
    rules: RulesVersion
    reward_config: RewardConfig = Field(default_factory=RewardConfig)
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_binary(self) -> bool:
        return len(self.outcomes) == 2 and len(self.token_ids) == 2

    @property
    def has_placeholder_outcome(self) -> bool:
        normalized = {outcome.strip().lower() for outcome in self.outcomes}
        return any(value in {"other", "placeholder", "tbd", "unnamed"} for value in normalized)

    def days_to_resolution(self, as_of: date) -> int | None:
        target = self.close_date or self.end_date
        if target is None:
            return None
        return (target - as_of).days


def hash_rules(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
