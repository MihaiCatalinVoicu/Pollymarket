from __future__ import annotations

from datetime import date

from src.registry.filtering import UniverseFilterPolicy, evaluate_market
from src.registry.models import MarketRecord, RewardConfig, RulesVersion


def _policy() -> UniverseFilterPolicy:
    return UniverseFilterPolicy(
        allowed_categories={"crypto", "finance", "tech", "economics"},
        blocked_categories={"sports", "politics", "geopolitics"},
        require_orderbook_enabled=True,
        require_fees_enabled=True,
        require_clear_rules=True,
        require_named_outcomes_only=True,
        require_binary_outcomes=True,
        min_open_interest=1000.0,
        min_volume_24h=500.0,
        max_days_to_resolution=90,
        blocked_title_substrings=("sports",),
        blocked_slug_substrings=("other",),
        blocked_market_types={"augmented_neg_risk"},
    )


def _market(**overrides) -> MarketRecord:
    payload = {
        "market_id": "m1",
        "title": "BTC above 100k on June 30?",
        "category": "crypto",
        "outcomes": ["Yes", "No"],
        "token_ids": ["1", "2"],
        "active": True,
        "closed": False,
        "resolved": False,
        "enable_order_book": True,
        "fees_enabled": True,
        "neg_risk": False,
        "neg_risk_augmented": False,
        "open_interest": 5000.0,
        "volume_24h": 10000.0,
        "close_date": date(2026, 6, 30),
        "rules": RulesVersion(
            rules_text="Resolves yes if BTC/USD on the specified source settles above 100000 on June 30, 2026.",
            rules_hash="abc",
        ),
        "reward_config": RewardConfig(),
    }
    payload.update(overrides)
    return MarketRecord.model_validate(payload)


def test_allows_narrow_binary_objective_market() -> None:
    decision = evaluate_market(_market(), _policy(), as_of=date(2026, 4, 1))
    assert decision.eligible is True
    assert decision.reasons == []


def test_blocks_placeholder_and_policy_category() -> None:
    decision = evaluate_market(
        _market(category="politics", outcomes=["Yes", "Other"], token_ids=["1", "2"]),
        _policy(),
        as_of=date(2026, 4, 1),
    )
    assert decision.eligible is False
    assert "category_blocked" in decision.reasons
    assert "placeholder_or_other_outcome" in decision.reasons

