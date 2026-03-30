from __future__ import annotations

from pydantic import BaseModel


class RiskPolicy(BaseModel):
    max_notional_per_market: float = 250.0
    max_notional_per_event: float = 500.0
    max_notional_per_category: float = 750.0
    max_inventory_skew_pct: float = 0.35
    max_unresolved_exposure: float = 1500.0
    max_rules_ambiguity_score: float = 0.20
    max_quote_age_seconds: float = 15.0
    max_ws_desync_seconds: float = 3.0
    max_api_reject_streak: int = 5
    max_cancel_failure_streak: int = 3
    max_daily_loss_usdc: float = 50.0
    max_weekly_loss_usdc: float = 150.0

