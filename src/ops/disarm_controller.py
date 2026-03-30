from __future__ import annotations

from typing import Any


def evaluate_disarm(runtime_ctx: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    disarm_cfg = (((cfg.get("polymarket") or {}).get("disarm")) or {})
    reasons: list[str] = []
    if runtime_ctx.get("heartbeat_failure"):
        reasons.append("heartbeat_failure")
    if runtime_ctx.get("geoblock_failure"):
        reasons.append("geoblock_failure")
    if runtime_ctx.get("auth_invalid"):
        reasons.append("auth_invalid")
    if float(runtime_ctx.get("ws_desync_seconds", 0.0)) > float(disarm_cfg.get("max_ws_desync_seconds", 3.0)):
        reasons.append("ws_desync_limit")
    if int(runtime_ctx.get("api_reject_streak", 0)) > int(disarm_cfg.get("max_api_reject_streak", 5)):
        reasons.append("api_reject_streak_limit")
    if int(runtime_ctx.get("cancel_failure_streak", 0)) > int(disarm_cfg.get("max_cancel_failure_streak", 3)):
        reasons.append("cancel_failure_streak_limit")
    if float(runtime_ctx.get("daily_loss_usdc", 0.0)) > float(disarm_cfg.get("max_daily_loss_usdc", 50.0)):
        reasons.append("daily_loss_limit")
    if float(runtime_ctx.get("weekly_loss_usdc", 0.0)) > float(disarm_cfg.get("max_weekly_loss_usdc", 150.0)):
        reasons.append("weekly_loss_limit")
    return {"disarm": bool(reasons), "reasons": reasons}
