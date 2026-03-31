from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from src.common.paths import RUN_MANIFEST_ROOT, RUNTIME_ROOT, SHADOW_ROOT
from src.config import Settings
from src.execution.order_router import OrderIntent, OrderRouter
from src.inventory.manager import InventoryManager, InventoryState
from src.ops.promotion_controller import evaluate_strategy_state, load_promotion_cfg, write_strategy_arming
from src.ops.run_manifest import build_run_completed_manifest, manifest_artifact_link, write_run_manifest
from src.ops.runtime_event_logger import RunContext, emit_event, set_run_context
from src.registry.filtering import UniverseFilterPolicy, tag_penalty
from src.registry.models import MarketRecord, RewardConfig
from src.risk.governor import RiskGovernor, RiskSnapshot
from src.risk.policy import RiskPolicy
from src.strategy.latarb_v1.overlay import LatencyDecision
from src.strategy.mm_v1.fair_value import BookSnapshot, FairValueDecision, FairValueInputs, compute_fair_value
from src.strategy.mm_v1.quote_engine import QuoteIntent, QuoteRequest, build_quotes
from src.strategy.parity_v1.engine import ParityInputs, compute_parity

try:
    from py_clob_client.client import ClobClient
except ImportError:
    ClobClient = None


class TokenShadowState(BaseModel):
    token_id: str
    outcome: str
    best_bid: float | None = None
    best_ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    midpoint: float | None = None
    last_trade_price: float | None = None


class ShadowMarketState(BaseModel):
    market_id: str
    title: str
    category: str | None = None
    event_id: str | None = None
    tick_size: float
    primary: TokenShadowState
    complementary: TokenShadowState
    fee_rate_bps: float = 0.0
    reward_config: RewardConfig = Field(default_factory=RewardConfig)
    time_to_resolution_days: float = 30.0
    rules_ambiguity_score: float = 0.0
    open_interest: float = 0.0
    volume_24h: float = 0.0


class SimulatedFill(BaseModel):
    side: str
    price: float
    requested_size: float
    filled_size: float
    fill_ratio: float
    queue_ratio: float
    notional_usdc: float
    spread_capture_usdc: float
    adverse_selection_usdc: float


class ShadowMarketResult(BaseModel):
    market_id: str
    title: str
    category: str | None = None
    candidate_score: float
    fair_value: float
    midpoint: float
    microprice: float
    full_set_parity_bps: float
    quoting_mode: str
    quotes: list[QuoteIntent] = Field(default_factory=list)
    routed_orders: list[dict[str, Any]] = Field(default_factory=list)
    simulated_fills: list[SimulatedFill] = Field(default_factory=list)
    spread_capture_usdc: float = 0.0
    adverse_selection_usdc: float = 0.0
    reward_usdc: float = 0.0
    rebate_usdc: float = 0.0
    net_edge_usdc: float = 0.0
    inventory_before: dict[str, float] = Field(default_factory=dict)
    inventory_after: dict[str, float] = Field(default_factory=dict)
    inventory_plan_before: dict[str, Any] = Field(default_factory=dict)
    inventory_plan_after: dict[str, Any] = Field(default_factory=dict)
    parity_notes: list[str] = Field(default_factory=list)
    blocked_by: list[str] = Field(default_factory=list)
    risk_decision: dict[str, Any] = Field(default_factory=dict)
    latency_overlay: dict[str, Any] = Field(default_factory=dict)


class ShadowRunReport(BaseModel):
    run_id: str
    generated_at: str
    current_phase: str
    selected_market_ids: list[str]
    inventory_path_validated: bool
    geoblock_ok: bool
    auth_ok: bool
    market_results: list[ShadowMarketResult]
    metrics_summary: dict[str, Any]
    notes: list[str] = Field(default_factory=list)


class MarketStateProvider(Protocol):
    def fetch_market_state(self, record: MarketRecord) -> ShadowMarketState:
        ...


class StaticMarketStateProvider:
    def __init__(self, states: dict[str, ShadowMarketState]) -> None:
        self.states = states

    def fetch_market_state(self, record: MarketRecord) -> ShadowMarketState:
        market_id = record.market_id or ""
        if market_id not in self.states:
            raise KeyError(f"missing static state for {market_id}")
        return self.states[market_id]


class LiveClobMarketStateProvider:
    def __init__(self, settings: Settings) -> None:
        if ClobClient is None:
            raise RuntimeError('Install optional shadow dependencies with `py -m pip install -e ".[clob]"`.')
        self.client = ClobClient(settings.clob_api_url, settings.chain_id)

    @staticmethod
    def _extract_best(book: Any) -> tuple[float | None, float | None, float | None, float | None]:
        bids = getattr(book, "bids", None) or []
        asks = getattr(book, "asks", None) or []
        best_bid = float(bids[0].price) if bids else None
        best_ask = float(asks[0].price) if asks else None
        bid_size = float(bids[0].size) if bids else None
        ask_size = float(asks[0].size) if asks else None
        return best_bid, best_ask, bid_size, ask_size

    def _load_token(self, token_id: str, outcome: str) -> TokenShadowState:
        book = self.client.get_order_book(token_id)
        midpoint_payload = self.client.get_midpoint(token_id)
        best_bid, best_ask, bid_size, ask_size = self._extract_best(book)
        midpoint = midpoint_payload.get("mid") if isinstance(midpoint_payload, dict) else None
        midpoint_value = float(midpoint) if midpoint is not None else None
        return TokenShadowState(
            token_id=token_id,
            outcome=outcome,
            best_bid=best_bid,
            best_ask=best_ask,
            bid_size=bid_size,
            ask_size=ask_size,
            midpoint=midpoint_value,
            last_trade_price=midpoint_value,
        )

    def fetch_market_state(self, record: MarketRecord) -> ShadowMarketState:
        if not record.market_id or len(record.token_ids) < 2 or len(record.outcomes) < 2:
            raise ValueError("record must contain market_id, two token_ids, and two outcomes")
        primary = self._load_token(record.token_ids[0], record.outcomes[0])
        complementary = self._load_token(record.token_ids[1], record.outcomes[1])
        fee_rate_bps = float(self.client.get_fee_rate_bps(record.token_ids[0]))
        tick_size = float(record.tick_size or self.client.get_tick_size(record.token_ids[0]) or 0.01)
        return ShadowMarketState(
            market_id=record.market_id,
            title=record.title,
            category=record.category,
            event_id=record.event_id,
            tick_size=tick_size,
            primary=primary,
            complementary=complementary,
            fee_rate_bps=fee_rate_bps,
            reward_config=record.reward_config,
            time_to_resolution_days=float(record.days_to_resolution(datetime.now(timezone.utc).date()) or 30.0),
            rules_ambiguity_score=_rules_ambiguity_score(record.rules.rules_text),
            open_interest=record.open_interest,
            volume_24h=record.volume_24h,
        )


class ShadowAConfig(BaseModel):
    quoting_mode: str = "one_sided"
    max_markets: int = 5
    base_quote_size: float = 5.0
    min_quote_size: float = 1.0
    market_seed_usdc: float = 25.0
    cycle_minutes: int = 1
    maker_rebate_bps: float = 0.10
    current_phase: str = "shadow_live"
    shadow_days: float = 1.0
    max_markets_per_event: int = 1
    max_markets_per_theme: int = 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _promotion_cfg_path(settings: Settings) -> Path:
    return Path(settings.allowlist_path).resolve().parent / "promotion_controller.yaml"


def _rules_ambiguity_score(rules_text: str) -> float:
    normalized = rules_text.lower()
    score = 0.0
    for term in ("discretion", "interpret", "review", "manual", "unclear", "subject to"):
        if term in normalized:
            score += 0.08
    if len(normalized.strip()) < 120:
        score += 0.05
    return min(score, 0.50)


def _reward_score(config: RewardConfig) -> float:
    score = 0.0
    if config.reward_allocation:
        score += min(float(config.reward_allocation) / 2000.0, 0.60)
    if config.max_incentive_spread:
        score += 0.20
    if config.min_incentive_size:
        score += 0.20
    return min(score, 1.0)


def _theme_key(record: MarketRecord) -> str:
    title = (record.title or "").lower()
    tags = [tag.lower() for tag in record.tags]
    for tag in tags:
        if tag in {"crypto", "finance", "tech", "economics", "economy", "featured", "pre-market", "all"}:
            continue
        if len(tag) >= 4:
            return tag
    for token in title.replace("?", " ").replace(",", " ").replace("(", " ").replace(")", " ").split():
        cleaned = token.strip("$%").lower()
        if cleaned in {
            "will",
            "market",
            "cap",
            "fdv",
            "perform",
            "airdrop",
            "before",
            "after",
            "by",
            "one",
            "day",
            "launch",
            "yes",
            "no",
        }:
            continue
        if len(cleaned) >= 4:
            return cleaned
    return record.market_id or record.slug or record.title


def _candidate_score(record: MarketRecord, state: ShadowMarketState, *, policy: UniverseFilterPolicy | None = None) -> float:
    midpoint = state.primary.midpoint or state.complementary.midpoint or 0.50
    spread = 0.10
    if state.primary.best_bid is not None and state.primary.best_ask is not None:
        spread = max(state.primary.best_ask - state.primary.best_bid, 0.0)
    liquidity_score = min(record.open_interest / 10_000.0, 1.0) * 0.5 + min(record.volume_24h / 10_000.0, 1.0) * 0.5
    spread_score = max(0.0, 1.0 - min(spread, 0.20) / 0.20)
    reward_score = _reward_score(record.reward_config)
    midpoint_score = 1.0 if 0.10 <= midpoint <= 0.90 else 0.40
    resolution_score = max(0.0, 1.0 - min(state.time_to_resolution_days, 120.0) / 120.0)
    ambiguity_penalty = min(state.rules_ambiguity_score, 0.35)
    soft_tag_penalty = tag_penalty(record, policy) if policy else 0.0
    score = (
        (0.34 * liquidity_score)
        + (0.24 * reward_score)
        + (0.18 * spread_score)
        + (0.10 * midpoint_score)
        + (0.14 * resolution_score)
        - ambiguity_penalty
        - soft_tag_penalty
    )
    return round(max(score, 0.0), 6)


def _select_diverse_candidates(
    states: list[tuple[MarketRecord, ShadowMarketState, float]],
    *,
    max_markets: int,
    max_markets_per_event: int,
    max_markets_per_theme: int,
) -> list[tuple[MarketRecord, ShadowMarketState, float]]:
    if len(states) <= max_markets:
        return states

    selected: list[tuple[MarketRecord, ShadowMarketState, float]] = []
    event_counts: dict[str, int] = {}
    theme_counts: dict[str, int] = {}

    def can_take(record: MarketRecord) -> bool:
        event_key = record.event_id or record.market_id or ""
        theme = _theme_key(record)
        return (
            event_counts.get(event_key, 0) < max_markets_per_event
            and theme_counts.get(theme, 0) < max_markets_per_theme
        )

    def mark_taken(record: MarketRecord) -> None:
        event_key = record.event_id or record.market_id or ""
        theme = _theme_key(record)
        event_counts[event_key] = event_counts.get(event_key, 0) + 1
        theme_counts[theme] = theme_counts.get(theme, 0) + 1

    for candidate in states:
        record = candidate[0]
        if can_take(record):
            selected.append(candidate)
            mark_taken(record)
            if len(selected) >= max_markets:
                return selected

    for candidate in states:
        if candidate in selected:
            continue
        selected.append(candidate)
        if len(selected) >= max_markets:
            break
    return selected


def _load_inventory_validation_flag(path: Path = RUNTIME_ROOT / "venue_smoke.json") -> tuple[bool, list[str]]:
    if not path.exists():
        return False, ["venue_smoke_missing"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    issues: list[str] = []
    split_merge_ok = bool(((payload.get("split_merge") or {}).get("ok")))
    if not split_merge_ok:
        issues.append("inventory_smoke_not_passed")
    post_only_ok = bool(((payload.get("post_only_order") or {}).get("ok")))
    if not post_only_ok:
        issues.append("order_smoke_not_passed")
    return split_merge_ok and post_only_ok, issues


def _seed_inventory(config: ShadowAConfig, reward_config: RewardConfig) -> tuple[InventoryState, dict[str, Any]]:
    target_pairs = max(config.base_quote_size, float(reward_config.min_incentive_size or 0.0), config.min_quote_size)
    manager = InventoryManager()
    state = InventoryState(usdc_balance=max(config.market_seed_usdc, target_pairs * 2.0))
    plan = manager.plan(state, target_pairs=target_pairs)
    if plan.split_usdc > 0:
        state.usdc_balance -= plan.split_usdc
        state.yes_tokens += plan.split_usdc
        state.no_tokens += plan.split_usdc
    return state, {
        "target_pairs": target_pairs,
        "plan": plan.model_dump(),
    }


def _simulate_fill(
    quote: QuoteIntent,
    *,
    tick_size: float,
    book: TokenShadowState,
    fair_value: FairValueDecision,
    ambiguity_score: float,
) -> SimulatedFill:
    if quote.side == "buy":
        touch_price = book.best_bid
        queue_size = book.bid_size or 0.0
        improved = touch_price is not None and quote.price > touch_price
        at_touch = touch_price is not None and abs(quote.price - touch_price) < max(tick_size / 2.0, 1e-9)
    else:
        touch_price = book.best_ask
        queue_size = book.ask_size or 0.0
        improved = touch_price is not None and quote.price < touch_price
        at_touch = touch_price is not None and abs(quote.price - touch_price) < max(tick_size / 2.0, 1e-9)

    if touch_price is None:
        base_ratio = 0.02
    elif improved:
        base_ratio = 0.18
    elif at_touch:
        base_ratio = 0.08
    else:
        base_ratio = 0.02

    queue_ratio = queue_size / max(quote.size, 1e-6)
    queue_factor = max(0.25, 1.0 / (1.0 + queue_ratio))
    fill_ratio = min(0.35, base_ratio * queue_factor)
    filled_size = round(quote.size * fill_ratio, 6)
    notional = round(filled_size * quote.price, 6)
    if quote.side == "buy":
        spread_capture = max(0.0, fair_value.fair_value - quote.price) * filled_size
    else:
        spread_capture = max(0.0, quote.price - fair_value.fair_value) * filled_size
    midpoint_gap = abs(fair_value.fair_value - fair_value.midpoint)
    adverse_selection = filled_size * ((midpoint_gap * 0.50) + (ambiguity_score * 0.01))
    return SimulatedFill(
        side=quote.side,
        price=quote.price,
        requested_size=quote.size,
        filled_size=filled_size,
        fill_ratio=round(fill_ratio, 6),
        queue_ratio=round(queue_ratio, 6),
        notional_usdc=notional,
        spread_capture_usdc=round(spread_capture, 6),
        adverse_selection_usdc=round(adverse_selection, 6),
    )


def _estimate_reward_usdc(
    quote: QuoteIntent,
    *,
    config: ShadowAConfig,
    reward_config: RewardConfig,
    fair_value: FairValueDecision,
) -> float:
    allocation = float(reward_config.reward_allocation or 0.0)
    max_spread = float(reward_config.max_incentive_spread or 0.0)
    if allocation <= 0.0 or max_spread <= 0.0:
        return 0.0
    min_size = max(float(reward_config.min_incentive_size or config.min_quote_size), 1e-6)
    quote_width_bps = abs(quote.price - fair_value.fair_value) / max(fair_value.fair_value, 0.01) * 20_000.0
    quality = max(0.0, 1.0 - (quote_width_bps / max_spread))
    size_factor = min(1.0, quote.size / min_size)
    midpoint = fair_value.midpoint
    if config.quoting_mode == "one_sided":
        sidedness_factor = 0.60 if 0.10 <= midpoint <= 0.90 else 0.0
    else:
        sidedness_factor = 1.0
    cycle_fraction = config.cycle_minutes / 1440.0
    return round(allocation * cycle_fraction * quality * size_factor * sidedness_factor, 6)


def _estimate_rebate_usdc(fill: SimulatedFill, *, maker_rebate_bps: float) -> float:
    if fill.filled_size <= 0:
        return 0.0
    return round(fill.notional_usdc * maker_rebate_bps / 10_000.0, 6)


def _serialize_inventory(state: InventoryState) -> dict[str, float]:
    return {
        "usdc_balance": round(state.usdc_balance, 6),
        "yes_tokens": round(state.yes_tokens, 6),
        "no_tokens": round(state.no_tokens, 6),
        "paired_tokens": round(state.paired_tokens, 6),
        "skew_pct": round(state.skew_pct, 6),
    }


def _market_result(
    record: MarketRecord,
    state: ShadowMarketState,
    *,
    config: ShadowAConfig,
    risk_governor: RiskGovernor,
    policy: UniverseFilterPolicy | None = None,
) -> ShadowMarketResult:
    inventory_state, inventory_seed = _seed_inventory(config, state.reward_config)
    inventory_before = _serialize_inventory(inventory_state)

    fair_value = compute_fair_value(
        FairValueInputs(
            primary=BookSnapshot(
                best_bid=state.primary.best_bid,
                best_ask=state.primary.best_ask,
                bid_size=state.primary.bid_size,
                ask_size=state.primary.ask_size,
            ),
            complementary_midpoint=state.complementary.midpoint,
            inventory_skew=inventory_state.skew_pct,
            ambiguity_score=state.rules_ambiguity_score,
            reward_score=_reward_score(state.reward_config),
            time_to_resolution_days=state.time_to_resolution_days,
            last_trade_price=state.primary.last_trade_price,
        )
    )
    parity = compute_parity(
        ParityInputs(
            yes_bid=state.primary.best_bid or 0.0,
            yes_ask=state.primary.best_ask or 1.0,
            no_bid=state.complementary.best_bid or 0.0,
            no_ask=state.complementary.best_ask or 1.0,
            fee_rate=state.fee_rate_bps / 10_000.0,
            paired_inventory=inventory_state.paired_tokens,
            book_unwind_value=(state.primary.best_bid or 0.0) + (state.complementary.best_bid or 0.0),
        )
    )
    risk_decision = risk_governor.evaluate(
        RiskSnapshot(
            market_notional=config.base_quote_size * fair_value.fair_value,
            event_notional=config.base_quote_size,
            category_notional=config.base_quote_size,
            inventory_skew_pct=abs(inventory_state.skew_pct),
            unresolved_exposure=config.market_seed_usdc,
            rules_ambiguity_score=state.rules_ambiguity_score,
        )
    )

    candidate_score = _candidate_score(record, state, policy=policy)
    result = ShadowMarketResult(
        market_id=state.market_id,
        title=state.title,
        category=state.category,
        candidate_score=candidate_score,
        fair_value=round(fair_value.fair_value, 6),
        midpoint=round(fair_value.midpoint, 6),
        microprice=round(fair_value.microprice, 6),
        full_set_parity_bps=round(max(parity.full_set_buy_edge, parity.full_set_sell_edge, 0.0) * 10_000.0, 6),
        quoting_mode=config.quoting_mode,
        inventory_before=inventory_before,
        inventory_plan_before=inventory_seed,
        parity_notes=list(parity.notes),
        risk_decision=risk_decision.model_dump(),
        latency_overlay=LatencyDecision(reason="shadow_a_passive_only").model_dump(),
    )
    if not risk_decision.allow_trading:
        result.blocked_by.extend(risk_decision.reasons)
        result.inventory_after = inventory_before
        result.inventory_plan_after = {"plan": InventoryManager().plan(inventory_state, target_pairs=inventory_seed["target_pairs"]).model_dump()}
        return result

    quotes = build_quotes(
        QuoteRequest(
            fair_value=fair_value.fair_value,
            best_bid=state.primary.best_bid,
            best_ask=state.primary.best_ask,
            tick_size=state.tick_size,
            base_size=max(config.base_quote_size, inventory_seed["target_pairs"]),
            min_size=config.min_quote_size,
            max_width_bps=min(float(state.reward_config.max_incentive_spread or 100.0), 100.0),
            skew=inventory_state.skew_pct,
            quoting_mode=config.quoting_mode,
        )
    )
    router = OrderRouter()
    routed_orders: list[dict[str, Any]] = []
    fills: list[SimulatedFill] = []
    reward_total = 0.0
    rebate_total = 0.0
    spread_total = 0.0
    adverse_total = 0.0
    primary_balance = inventory_state.yes_tokens

    for quote in quotes:
        routed = router.prepare_order(
            OrderIntent(
                market_id=state.market_id,
                asset_id=state.primary.token_id,
                side=quote.side,
                price=quote.price,
                size=quote.size,
                tif=quote.tif,
                post_only=quote.post_only,
            ),
            tick_size=state.tick_size,
            best_bid=state.primary.best_bid,
            best_ask=state.primary.best_ask,
        )
        routed_orders.append({"quote": quote.model_dump(), "router": routed.model_dump()})
        if not routed.accepted:
            result.blocked_by.extend(routed.reasons)
            continue
        fill = _simulate_fill(
            quote,
            tick_size=state.tick_size,
            book=state.primary,
            fair_value=fair_value,
            ambiguity_score=state.rules_ambiguity_score,
        )
        fills.append(fill)
        spread_total += fill.spread_capture_usdc
        adverse_total += fill.adverse_selection_usdc
        reward_total += _estimate_reward_usdc(quote, config=config, reward_config=state.reward_config, fair_value=fair_value)
        rebate_total += _estimate_rebate_usdc(fill, maker_rebate_bps=config.maker_rebate_bps)

        if quote.side == "buy":
            inventory_state.usdc_balance = max(0.0, inventory_state.usdc_balance - fill.notional_usdc)
            inventory_state.yes_tokens += fill.filled_size
        else:
            sold_size = min(primary_balance, fill.filled_size)
            inventory_state.usdc_balance += sold_size * quote.price
            inventory_state.yes_tokens = max(0.0, inventory_state.yes_tokens - sold_size)
            primary_balance = inventory_state.yes_tokens

    result.quotes = quotes
    result.routed_orders = routed_orders
    result.simulated_fills = fills
    result.spread_capture_usdc = round(spread_total, 6)
    result.adverse_selection_usdc = round(adverse_total, 6)
    result.reward_usdc = round(reward_total, 6)
    result.rebate_usdc = round(rebate_total, 6)
    result.net_edge_usdc = round(spread_total - adverse_total + reward_total + rebate_total, 6)
    result.inventory_after = _serialize_inventory(inventory_state)
    result.inventory_plan_after = {
        "plan": InventoryManager().plan(inventory_state, target_pairs=inventory_seed["target_pairs"]).model_dump()
    }
    return result


def _aggregate_metrics(
    report: list[ShadowMarketResult],
    *,
    config: ShadowAConfig,
    inventory_path_validated: bool,
    geoblock_ok: bool,
    auth_ok: bool,
) -> dict[str, Any]:
    spread_capture = sum(item.spread_capture_usdc for item in report)
    adverse_selection = sum(item.adverse_selection_usdc for item in report)
    reward_total = sum(item.reward_usdc for item in report)
    rebate_total = sum(item.rebate_usdc for item in report)
    net_edge_ex_rewards = spread_capture + rebate_total - adverse_selection
    net_edge = net_edge_ex_rewards + reward_total
    total_quotes = sum(len(item.quotes) for item in report)
    rejected_quotes = sum(
        1
        for item in report
        for routed in item.routed_orders
        if not bool(((routed.get("router") or {}).get("accepted")))
    )
    market_edges = [abs(item.net_edge_usdc) for item in report if abs(item.net_edge_usdc) > 0]
    market_concentration = max(market_edges) / sum(market_edges) if market_edges else 0.0
    max_skew = max((abs(item.inventory_after.get("skew_pct", 0.0)) for item in report), default=0.0)
    blocked: list[str] = []
    if not report:
        blocked.append("no_markets_selected")
    if rejected_quotes:
        blocked.append("shadow_quote_rejections")

    return {
        "quote_edge_net": round(net_edge, 6),
        "spread_capture_usdc": round(spread_capture, 6),
        "reward_usdc": round(reward_total, 6),
        "rebate_usdc": round(rebate_total, 6),
        "net_edge_ex_rewards_usdc": round(net_edge_ex_rewards, 6),
        "adverse_selection_usdc": round(adverse_selection, 6),
        "inventory_skew_pct": round(max_skew, 6),
        "full_set_parity_bps": round(max((item.full_set_parity_bps for item in report), default=0.0), 6),
        "stale_take_pnl_usdc": 0.0,
        "ws_desync_ms": 0,
        "heartbeat_gap_ms": 0,
        "reject_ratio": round((rejected_quotes / total_quotes), 6) if total_quotes else 0.0,
        "cancel_ratio": 0.0,
        "settlement_lag_minutes": 0.0,
        "reconciliation_clean": True,
        "inventory_path_validated": inventory_path_validated,
        "heartbeat_healthy": True,
        "geoblock_ok": geoblock_ok,
        "auth_ok": auth_ok,
        "current_phase": config.current_phase,
        "shadow_days": config.shadow_days,
        "market_concentration_pct": round(market_concentration, 6),
        "mode_distribution": {config.quoting_mode: len(report)},
        "blocked_by": blocked,
    }


def run_shadow_a(
    records: list[MarketRecord],
    *,
    settings: Settings,
    config: ShadowAConfig | None = None,
    provider: MarketStateProvider | None = None,
    geoblock_ok: bool = True,
    auth_ok: bool = True,
) -> ShadowRunReport:
    cfg = config or ShadowAConfig()
    live_provider = provider or LiveClobMarketStateProvider(settings)
    policy = UniverseFilterPolicy.from_yaml(settings.allowlist_path, settings.denylist_path)
    inventory_path_validated, inventory_notes = _load_inventory_validation_flag()
    run_id = f"shadow-a-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    context = RunContext(environment=settings.environment, run_id=run_id)
    set_run_context(context)
    emit_event("shadow_a_started", payload={"candidate_markets": len(records), "mode": cfg.quoting_mode})

    states: list[tuple[MarketRecord, ShadowMarketState, float]] = []
    notes = list(inventory_notes)
    for record in records:
        try:
            state = live_provider.fetch_market_state(record)
        except Exception as exc:
            notes.append(f"{record.market_id or record.slug or record.title}: state_fetch_failed: {exc}")
            continue
        states.append((record, state, _candidate_score(record, state, policy=policy)))

    states.sort(key=lambda item: item[2], reverse=True)
    selected = _select_diverse_candidates(
        states,
        max_markets=cfg.max_markets,
        max_markets_per_event=cfg.max_markets_per_event,
        max_markets_per_theme=cfg.max_markets_per_theme,
    )
    risk_governor = RiskGovernor(RiskPolicy.model_validate(settings.risk.model_dump()))
    results = [
        _market_result(record, state, config=cfg, risk_governor=risk_governor, policy=policy)
        for record, state, _ in selected
    ]
    metrics_summary = _aggregate_metrics(
        results,
        config=cfg,
        inventory_path_validated=inventory_path_validated,
        geoblock_ok=geoblock_ok,
        auth_ok=auth_ok,
    )
    outcome_hint = "expand_oos" if metrics_summary["quote_edge_net"] >= 0 else "fix_now"
    report = ShadowRunReport(
        run_id=run_id,
        generated_at=_utc_now(),
        current_phase=cfg.current_phase,
        selected_market_ids=[item.market_id for item in results],
        inventory_path_validated=inventory_path_validated,
        geoblock_ok=geoblock_ok,
        auth_ok=auth_ok,
        market_results=results,
        metrics_summary=metrics_summary,
        notes=notes,
    )

    report_path = SHADOW_ROOT / f"{run_id}.json"
    write_shadow_run_report(report_path, report)

    manifest = build_run_completed_manifest(
        context,
        run_type="runtime_review",
        evaluation_phase=cfg.current_phase,
        outcome_hint=outcome_hint,
        metrics_summary=report.metrics_summary,
        artifact_links=[manifest_artifact_link(report_path, "shadow_a_report")],
        next_phase_hint="shadow_live",
    )
    manifest_path = RUN_MANIFEST_ROOT / f"{run_id}_run_manifest_v1.json"
    write_run_manifest(manifest_path, manifest)

    arming_path = RUNTIME_ROOT / "strategy_arming.json"
    previous_state = "PAPER_ONLY"
    if arming_path.exists():
        try:
            previous_payload = json.loads(arming_path.read_text(encoding="utf-8"))
            previous_state = str((((previous_payload.get("polymarket") or {}).get("polymarket_mm_v1") or {}).get("state")) or previous_state)
        except json.JSONDecodeError:
            notes.append("existing_strategy_arming_invalid_json")
    promotion_state = evaluate_strategy_state(
        "polymarket_mm_v1",
        "polymarket",
        report.metrics_summary,
        load_promotion_cfg(_promotion_cfg_path(settings)),
    )
    payload = {
        "polymarket": {
            "polymarket_mm_v1": {
                "state_before": previous_state,
                **promotion_state,
            }
        }
    }
    write_strategy_arming(arming_path, payload)
    emit_event(
        "shadow_a_completed",
        payload={
            "selected_markets": report.selected_market_ids,
            "quote_edge_net": report.metrics_summary["quote_edge_net"],
            "promotion_state": promotion_state["state"],
            "report_path": str(report_path),
            "manifest_path": str(manifest_path),
        },
    )
    return report


def write_shadow_run_report(path: str | Path, report: ShadowRunReport) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report.model_dump(mode="json"), indent=2), encoding="utf-8")
    return output
