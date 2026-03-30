from __future__ import annotations

from pydantic import BaseModel, Field


class AccountReconciliationSnapshot(BaseModel):
    open_orders: int = 0
    trade_count: int = 0
    positions_count: int = 0
    reward_usdc: float = 0.0
    rebate_usdc: float = 0.0
    reconciliation_clean: bool = True
    issues: list[str] = Field(default_factory=list)


class AccountReconciler:
    def summarize(
        self,
        *,
        open_orders: list[dict],
        trades: list[dict],
        positions: list[dict],
        rewards: list[dict] | None = None,
    ) -> AccountReconciliationSnapshot:
        rewards = rewards or []
        reward_total = sum(float(item.get("reward_usdc", 0.0)) for item in rewards)
        rebate_total = sum(float(item.get("rebate_usdc", 0.0)) for item in rewards)
        issues: list[str] = []
        if any("error" in item for item in open_orders):
            issues.append("open_order_payload_error")
        return AccountReconciliationSnapshot(
            open_orders=len(open_orders),
            trade_count=len(trades),
            positions_count=len(positions),
            reward_usdc=reward_total,
            rebate_usdc=rebate_total,
            reconciliation_clean=not issues,
            issues=issues,
        )
