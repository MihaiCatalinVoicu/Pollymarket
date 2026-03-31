from __future__ import annotations

from datetime import date

from src.registry.filtering import UniverseFilterPolicy, evaluate_market, infer_market_category
from src.registry.models import MarketRecord, RewardConfig, RulesVersion
from src.registry.service import normalize_market


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
        blocked_tag_substrings=("pop-culture", "politics"),
        category_inference_keywords={
            "crypto": ("bitcoin", "btc", "ethereum", "eth", "crypto"),
            "finance": ("fed", "cpi", "ipo", "finance"),
            "tech": ("openai", "ai", "tech"),
            "economics": ("economy", "recession", "gdp"),
        },
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


def test_infers_category_from_title_and_tags_when_gamma_category_is_missing() -> None:
    market = _market(category=None, title="Will bitcoin hit $150k by July 1?", tags=["featured"])
    assert infer_market_category(market, _policy()) == "crypto"


def test_blocks_event_grouping_noise_via_tags() -> None:
    decision = evaluate_market(
        _market(category=None, title="Will bitcoin hit $1m before GTA VI?", tags=["pop-culture", "crypto"]),
        _policy(),
        as_of=date(2026, 4, 1),
    )
    assert decision.eligible is False
    assert "tag_blocked" in decision.reasons


def test_normalize_market_parses_gamma_string_lists_and_event_tags() -> None:
    raw = {
        "id": "531202",
        "question": "BitBoy convicted?",
        "slug": "bitboy-convicted",
        "eventId": "21662",
        "outcomes": "[\"Yes\", \"No\"]",
        "clobTokenIds": "[\"1\", \"2\"]",
        "enableOrderBook": True,
        "feesEnabled": False,
        "closed": False,
        "active": True,
        "liquidity": "9231.67413",
        "volume24hr": 167520.3176620002,
        "orderPriceMinTickSize": 0.001,
        "rewardsMinSize": 20,
        "rewardsMaxSpread": 3.5,
        "clobRewards": [{"rewardsDailyRate": 0.001}],
        "description": "Resolves on official court records if the named conviction occurs before the deadline.",
    }
    event_lookup = {
        "21662": {
            "openInterest": 104918.501976,
            "enableOrderBook": True,
            "endDate": "2026-03-31T12:00:00Z",
            "tags": [{"label": "Finance", "slug": "finance"}, {"label": "Crypto", "slug": "crypto"}],
        }
    }

    market = normalize_market(raw, event_lookup=event_lookup)

    assert market.outcomes == ["Yes", "No"]
    assert market.token_ids == ["1", "2"]
    assert market.category == "finance"
    assert market.tags[:2] == ["finance", "crypto"]
    assert market.fees_enabled is True
    assert market.open_interest == 104918.501976
    assert market.tick_size == 0.001
