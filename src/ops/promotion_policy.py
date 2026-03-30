from __future__ import annotations

from typing import Iterable


PROMOTION_VERDICTS = {"PROMOTE", "PAPER_ONLY", "REJECT", "DISARM"}


def promotion_blocker_classes(blockers: Iterable[str] | None) -> list[str]:
    classes: list[str] = []
    seen: set[str] = set()
    for blocker in blockers or []:
        lowered = str(blocker or "").strip().lower()
        if lowered.startswith("missing_"):
            label = "data"
        elif lowered in {"insufficient_shadow_days", "insufficient_micro_live_days"}:
            label = "sample"
        elif lowered in {"negative_quote_edge", "negative_spread_capture", "rewards_only_pnl", "market_concentration_high"}:
            label = "performance"
        elif lowered in {
            "heartbeat_unhealthy",
            "geoblock_failed",
            "auth_invalid",
            "reconciliation_not_clean",
            "inventory_path_unvalidated",
            "hard_risk_governor_failure",
        }:
            label = "safety"
        else:
            label = "misc"
        if label not in seen:
            seen.add(label)
            classes.append(label)
    return classes


def promotion_verdict(*, eligible_for_arming: bool, blocker_classes: Iterable[str] | None = None, state_after: str = "") -> str:
    normalized_after = str(state_after or "").upper()
    classes = {str(value or "").strip().lower() for value in (blocker_classes or []) if str(value or "").strip()}
    if normalized_after in {"AUTO_DISARMED", "DISARMED"}:
        return "DISARM"
    if eligible_for_arming:
        return "PROMOTE"
    if classes & {"data", "safety"}:
        return "REJECT"
    return "PAPER_ONLY"
