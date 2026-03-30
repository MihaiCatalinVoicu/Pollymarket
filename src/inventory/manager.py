from __future__ import annotations

from pydantic import BaseModel


class InventoryState(BaseModel):
    usdc_balance: float = 0.0
    yes_tokens: float = 0.0
    no_tokens: float = 0.0

    @property
    def paired_tokens(self) -> float:
        return min(self.yes_tokens, self.no_tokens)

    @property
    def skew_pct(self) -> float:
        gross = self.yes_tokens + self.no_tokens
        if gross <= 0:
            return 0.0
        return (self.yes_tokens - self.no_tokens) / gross


class InventoryPlan(BaseModel):
    split_usdc: float = 0.0
    merge_pairs: float = 0.0
    redeem_winners: float = 0.0
    reasons: list[str] = []


class InventoryManager:
    def plan(self, state: InventoryState, *, target_pairs: float, resolved: bool = False, winning_side_tokens: float = 0.0) -> InventoryPlan:
        reasons: list[str] = []
        split_usdc = 0.0
        merge_pairs = 0.0
        redeem_winners = 0.0
        if resolved:
            redeem_winners = winning_side_tokens
            if state.paired_tokens > 0:
                merge_pairs = state.paired_tokens
            reasons.append("resolved_market_settlement")
            return InventoryPlan(split_usdc=split_usdc, merge_pairs=merge_pairs, redeem_winners=redeem_winners, reasons=reasons)
        if state.paired_tokens < target_pairs:
            split_usdc = min(state.usdc_balance, target_pairs - state.paired_tokens)
            reasons.append("split_to_rebuild_pairs")
        elif state.paired_tokens > target_pairs:
            merge_pairs = state.paired_tokens - target_pairs
            reasons.append("merge_excess_pairs")
        return InventoryPlan(split_usdc=split_usdc, merge_pairs=merge_pairs, redeem_winners=redeem_winners, reasons=reasons)

