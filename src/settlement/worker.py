from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class SettlementCase(BaseModel):
    market_id: str
    outcome: Literal["YES", "NO", "UNKNOWN"]
    yes_tokens: float = 0.0
    no_tokens: float = 0.0
    paired_tokens: float = 0.0


class SettlementPlan(BaseModel):
    redeem_yes: float = 0.0
    redeem_no: float = 0.0
    merge_pairs: float = 0.0
    payout_rate_yes: float = 0.0
    payout_rate_no: float = 0.0


class SettlementWorker:
    def plan(self, case: SettlementCase) -> SettlementPlan:
        if case.outcome == "YES":
            return SettlementPlan(redeem_yes=case.yes_tokens, merge_pairs=case.paired_tokens, payout_rate_yes=1.0, payout_rate_no=0.0)
        if case.outcome == "NO":
            return SettlementPlan(redeem_no=case.no_tokens, merge_pairs=case.paired_tokens, payout_rate_yes=0.0, payout_rate_no=1.0)
        return SettlementPlan(
            redeem_yes=case.yes_tokens,
            redeem_no=case.no_tokens,
            merge_pairs=case.paired_tokens,
            payout_rate_yes=0.5,
            payout_rate_no=0.5,
        )

