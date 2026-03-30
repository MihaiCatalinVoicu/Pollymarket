from __future__ import annotations

from pydantic import BaseModel, Field

from src.risk.policy import RiskPolicy


class RiskSnapshot(BaseModel):
    market_notional: float = 0.0
    event_notional: float = 0.0
    category_notional: float = 0.0
    inventory_skew_pct: float = 0.0
    unresolved_exposure: float = 0.0
    rules_ambiguity_score: float = 0.0
    quote_age_seconds: float = 0.0
    ws_desync_seconds: float = 0.0
    api_reject_streak: int = 0
    cancel_failure_streak: int = 0
    daily_loss_usdc: float = 0.0
    weekly_loss_usdc: float = 0.0
    heartbeat_ok: bool = True
    geoblock_ok: bool = True
    auth_ok: bool = True


class RiskDecision(BaseModel):
    allow_trading: bool
    hard_kill: bool
    cooldown: bool
    reasons: list[str] = Field(default_factory=list)


class RiskGovernor:
    def __init__(self, policy: RiskPolicy) -> None:
        self.policy = policy

    def evaluate(self, snapshot: RiskSnapshot) -> RiskDecision:
        reasons: list[str] = []
        hard_kill = False
        cooldown = False
        if not snapshot.heartbeat_ok:
            reasons.append("heartbeat_failure")
            hard_kill = True
        if not snapshot.geoblock_ok:
            reasons.append("geoblock_failure")
            hard_kill = True
        if not snapshot.auth_ok:
            reasons.append("auth_invalid")
            hard_kill = True
        if snapshot.market_notional > self.policy.max_notional_per_market:
            reasons.append("market_notional_limit")
        if snapshot.event_notional > self.policy.max_notional_per_event:
            reasons.append("event_notional_limit")
        if snapshot.category_notional > self.policy.max_notional_per_category:
            reasons.append("category_notional_limit")
        if abs(snapshot.inventory_skew_pct) > self.policy.max_inventory_skew_pct:
            reasons.append("inventory_skew_limit")
        if snapshot.unresolved_exposure > self.policy.max_unresolved_exposure:
            reasons.append("unresolved_exposure_limit")
        if snapshot.rules_ambiguity_score > self.policy.max_rules_ambiguity_score:
            reasons.append("rules_ambiguity_limit")
        if snapshot.quote_age_seconds > self.policy.max_quote_age_seconds:
            reasons.append("quote_age_limit")
        if snapshot.ws_desync_seconds > self.policy.max_ws_desync_seconds:
            reasons.append("ws_desync_limit")
        if snapshot.api_reject_streak > self.policy.max_api_reject_streak:
            reasons.append("api_reject_streak_limit")
            cooldown = True
        if snapshot.cancel_failure_streak > self.policy.max_cancel_failure_streak:
            reasons.append("cancel_failure_streak_limit")
            cooldown = True
        if snapshot.daily_loss_usdc > self.policy.max_daily_loss_usdc:
            reasons.append("daily_loss_limit")
            hard_kill = True
        if snapshot.weekly_loss_usdc > self.policy.max_weekly_loss_usdc:
            reasons.append("weekly_loss_limit")
            hard_kill = True
        return RiskDecision(allow_trading=not reasons, hard_kill=hard_kill, cooldown=cooldown, reasons=reasons)
