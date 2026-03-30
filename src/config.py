from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class RiskConfig(BaseModel):
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


class PromotionConfig(BaseModel):
    min_shadow_days: int = 21
    min_micro_live_days: int = 30
    min_quote_edge_net_usdc: float = 0.0
    min_spread_capture_usdc: float = 0.0
    min_net_edge_ex_rewards_usdc: float = 0.0
    max_market_concentration_pct: float = 0.40


class Settings(BaseModel):
    environment: str = "research"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/polymarket_bot"
    redis_url: str | None = None
    gamma_api_url: str = "https://gamma-api.polymarket.com"
    clob_api_url: str = "https://clob.polymarket.com"
    data_api_url: str = "https://data-api.polymarket.com"
    market_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    user_ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/user"
    chain_id: int = 137
    enable_live_trading: bool = False
    heartbeat_interval_seconds: int = 5
    heartbeat_stale_seconds: int = 10
    heartbeat_buffer_seconds: int = 5
    allowlist_path: str = "configs/market_allowlist.yaml"
    denylist_path: str = "configs/market_denylist.yaml"
    risk: RiskConfig = Field(default_factory=RiskConfig)
    promotion: PromotionConfig = Field(default_factory=PromotionConfig)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _env_override(raw: dict[str, Any], key: str, env_name: str, coerce: callable | None = None) -> None:
    value = os.getenv(env_name)
    if value in ("", None):
        return
    raw[key] = coerce(value) if coerce else value


def load_settings(path: str | Path | None = None) -> Settings:
    load_dotenv()
    config_path = Path(path or os.getenv("POLYMARKET_CONFIG_PATH", "config.yaml"))
    raw = _load_yaml(config_path)
    _env_override(raw, "environment", "POLYMARKET_ENV")
    _env_override(raw, "database_url", "POLYMARKET_DATABASE_URL")
    _env_override(raw, "redis_url", "POLYMARKET_REDIS_URL")
    _env_override(raw, "gamma_api_url", "POLYMARKET_GAMMA_API_URL")
    _env_override(raw, "clob_api_url", "POLYMARKET_CLOB_API_URL")
    _env_override(raw, "data_api_url", "POLYMARKET_DATA_API_URL")
    _env_override(raw, "market_ws_url", "POLYMARKET_MARKET_WS_URL")
    _env_override(raw, "user_ws_url", "POLYMARKET_USER_WS_URL")
    _env_override(raw, "chain_id", "POLYMARKET_CHAIN_ID", int)
    _env_override(raw, "enable_live_trading", "POLYMARKET_ENABLE_LIVE_TRADING", lambda v: v.lower() == "true")
    _env_override(raw, "heartbeat_interval_seconds", "POLYMARKET_HEARTBEAT_INTERVAL_SECONDS", int)
    _env_override(raw, "heartbeat_stale_seconds", "POLYMARKET_HEARTBEAT_STALE_SECONDS", int)
    _env_override(raw, "heartbeat_buffer_seconds", "POLYMARKET_HEARTBEAT_BUFFER_SECONDS", int)
    return Settings.model_validate(raw)


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))
