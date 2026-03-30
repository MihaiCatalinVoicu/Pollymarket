from __future__ import annotations

from src.inventory.manager import InventoryManager, InventoryState
from src.risk.governor import RiskGovernor, RiskSnapshot
from src.risk.policy import RiskPolicy
from src.settlement.worker import SettlementCase, SettlementWorker


def test_risk_governor_hard_kills_on_heartbeat_failure() -> None:
    governor = RiskGovernor(RiskPolicy())
    decision = governor.evaluate(RiskSnapshot(heartbeat_ok=False))
    assert decision.allow_trading is False
    assert decision.hard_kill is True
    assert "heartbeat_failure" in decision.reasons


def test_inventory_and_unknown_settlement_paths() -> None:
    inventory = InventoryManager().plan(InventoryState(usdc_balance=50, yes_tokens=1, no_tokens=1), target_pairs=10)
    settlement = SettlementWorker().plan(
        SettlementCase(market_id="m1", outcome="UNKNOWN", yes_tokens=3, no_tokens=4, paired_tokens=2)
    )
    assert inventory.split_usdc > 0
    assert settlement.payout_rate_yes == 0.5
    assert settlement.payout_rate_no == 0.5

