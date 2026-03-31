from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from pydantic import BaseModel, Field

from src.common.paths import REPORTS_ROOT
from src.config import Settings
from src.ops.runtime_event_logger import RunContext, emit_event, set_run_context
from src.registry.filtering import UniverseFilterPolicy
from src.registry.models import MarketRecord
from src.shadow.service import (
    LiveClobMarketStateProvider,
    MarketStateProvider,
    ShadowAConfig,
    build_discovery_candidate_pool,
    evaluate_live_book_quality,
)


class QuoteableMarketObservation(BaseModel):
    market_id: str
    title: str
    category: str | None = None
    event_id: str | None = None
    strict_eligible: bool = False
    metadata_score: float = 0.0
    quoteable: bool
    best_outcome: str | None = None
    best_spread: float | None = None
    best_normalized_spread_bps: float | None = None
    best_top_depth_shares: float = 0.0
    best_top_depth_notional: float = 0.0
    midpoint_consistency_bps: float | None = None
    reasons: list[str] = Field(default_factory=list)


class QuoteableWindowSample(BaseModel):
    sample_id: str
    sampled_at: str
    interval_minutes: int
    selection_mode: str
    input_markets: int
    strict_eligible_count: int
    metadata_candidate_pool_count: int
    metadata_fetch_limit: int
    fetched_market_states: int
    quoteable_count: int
    quoteable_ratio: float
    reason_counts: dict[str, int] = Field(default_factory=dict)
    observations: list[QuoteableMarketObservation] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class QuoteableWindowSummary(BaseModel):
    generated_at: str
    sample_count: int
    interval_minutes: int
    markets_seen: int
    markets_checked: int
    quoteable_count: int
    quoteable_ratio: float
    quoteable_minutes_by_market: dict[str, float] = Field(default_factory=dict)
    quoteable_windows: list[dict[str, Any]] = Field(default_factory=list)
    reason_counts: dict[str, int] = Field(default_factory=dict)
    best_markets_by_quoteable_time: list[dict[str, Any]] = Field(default_factory=list)
    best_hours_utc: list[dict[str, Any]] = Field(default_factory=list)
    best_dayparts_utc: list[dict[str, Any]] = Field(default_factory=list)
    median_normalized_spread_bps_when_quoteable: float | None = None
    median_depth_when_quoteable: float | None = None
    median_depth_shares_when_quoteable: float | None = None
    latest_sample: dict[str, Any] = Field(default_factory=dict)
    conclusion_hint: str = "insufficient_data"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _utc_now_z() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


def _daypart_for_hour(hour: int) -> str:
    if 0 <= hour <= 5:
        return "00-05"
    if 6 <= hour <= 11:
        return "06-11"
    if 12 <= hour <= 17:
        return "12-17"
    return "18-23"


def sample_quoteable_window(
    records: list[MarketRecord],
    *,
    settings: Settings,
    config: ShadowAConfig,
    selection_mode: str = "broad",
    strict_market_ids: set[str] | None = None,
    provider: MarketStateProvider | None = None,
    sampled_at: datetime | None = None,
) -> QuoteableWindowSample:
    sample_dt = (sampled_at or _utc_now()).astimezone(timezone.utc).replace(microsecond=0)
    strict_ids = {market_id for market_id in (strict_market_ids or set()) if market_id}
    policy = UniverseFilterPolicy.from_yaml(settings.allowlist_path, settings.denylist_path)
    live_provider = provider or LiveClobMarketStateProvider(settings)
    discovery_pool, discovery_summary = build_discovery_candidate_pool(
        records,
        policy=policy,
        config=config,
        strict_market_ids=strict_ids if selection_mode == "broad" else None,
        as_of=sample_dt.date(),
    )

    observations: list[QuoteableMarketObservation] = []
    reason_counts: Counter[str] = Counter()
    notes: list[str] = []
    for record, discovery_quality in discovery_pool:
        try:
            state = live_provider.fetch_market_state(record)
        except Exception as exc:
            notes.append(f"{record.market_id or record.slug or record.title}: state_fetch_failed: {exc}")
            reason_counts["state_fetch_failed"] += 1
            continue
        live_quality = evaluate_live_book_quality(state, config)
        if not live_quality.quoteable:
            reason_counts.update(live_quality.reasons)
        observations.append(
            QuoteableMarketObservation(
                market_id=str(record.market_id or ""),
                title=record.title,
                category=record.category,
                event_id=record.event_id,
                strict_eligible=discovery_quality.strict_eligible,
                metadata_score=discovery_quality.metadata_score,
                quoteable=live_quality.quoteable,
                best_outcome=live_quality.best_outcome,
                best_spread=live_quality.best_spread,
                best_normalized_spread_bps=live_quality.best_normalized_spread_bps,
                best_top_depth_shares=live_quality.best_top_depth_shares,
                best_top_depth_notional=live_quality.best_top_depth_notional,
                midpoint_consistency_bps=live_quality.midpoint_consistency_bps,
                reasons=list(live_quality.reasons),
            )
        )

    quoteable_count = sum(1 for item in observations if item.quoteable)
    fetched_market_states = len(observations)
    quoteable_ratio = round((quoteable_count / fetched_market_states), 6) if fetched_market_states else 0.0
    return QuoteableWindowSample(
        sample_id=f"qwm-{sample_dt.strftime('%Y%m%dT%H%M%SZ')}",
        sampled_at=sample_dt.isoformat().replace("+00:00", "Z"),
        interval_minutes=max(config.cycle_minutes, 1),
        selection_mode=selection_mode,
        input_markets=len(records),
        strict_eligible_count=int(discovery_summary["strict_eligible_count"]),
        metadata_candidate_pool_count=int(discovery_summary["metadata_candidate_pool_count"]),
        metadata_fetch_limit=int(discovery_summary["metadata_fetch_limit"]),
        fetched_market_states=fetched_market_states,
        quoteable_count=quoteable_count,
        quoteable_ratio=quoteable_ratio,
        reason_counts=dict(sorted(reason_counts.items())),
        observations=observations,
        notes=notes,
    )


def append_quoteable_sample(path: str | Path, sample: QuoteableWindowSample) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(sample.model_dump(mode="json"), ensure_ascii=True) + "\n")
    return output


def load_quoteable_samples(path: str | Path) -> list[QuoteableWindowSample]:
    source = Path(path)
    if not source.exists():
        return []
    samples: list[QuoteableWindowSample] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        samples.append(QuoteableWindowSample.model_validate_json(line))
    return samples


def summarize_quoteable_samples(samples: list[QuoteableWindowSample]) -> QuoteableWindowSummary:
    if not samples:
        return QuoteableWindowSummary(
            generated_at=_utc_now_z(),
            sample_count=0,
            interval_minutes=0,
            markets_seen=0,
            markets_checked=0,
            quoteable_count=0,
            quoteable_ratio=0.0,
            conclusion_hint="insufficient_data",
        )

    interval_minutes = max(int(samples[-1].interval_minutes or 0), 1)
    markets_seen: set[str] = set()
    total_observations = 0
    total_quoteable_observations = 0
    reason_counts: Counter[str] = Counter()
    quoteable_observations_by_market: dict[str, list[tuple[datetime, QuoteableMarketObservation]]] = defaultdict(list)
    market_titles: dict[str, str] = {}
    hour_counts: Counter[int] = Counter()
    daypart_counts: Counter[str] = Counter()
    quoteable_spreads: list[float] = []
    quoteable_depths: list[float] = []
    quoteable_depth_shares: list[float] = []

    for sample in samples:
        sampled_at = datetime.fromisoformat(sample.sampled_at.replace("Z", "+00:00"))
        for observation in sample.observations:
            total_observations += 1
            markets_seen.add(observation.market_id)
            market_titles[observation.market_id] = observation.title
            if observation.quoteable:
                total_quoteable_observations += 1
                quoteable_observations_by_market[observation.market_id].append((sampled_at, observation))
                hour_counts[sampled_at.hour] += 1
                daypart_counts[_daypart_for_hour(sampled_at.hour)] += 1
                if observation.best_normalized_spread_bps is not None:
                    quoteable_spreads.append(float(observation.best_normalized_spread_bps))
                quoteable_depths.append(float(observation.best_top_depth_notional))
                quoteable_depth_shares.append(float(observation.best_top_depth_shares))
            else:
                reason_counts.update(observation.reasons)

    quoteable_minutes_by_market = {
        market_id: round(len(observations) * interval_minutes, 6)
        for market_id, observations in quoteable_observations_by_market.items()
    }

    windows: list[dict[str, Any]] = []
    max_gap_seconds = interval_minutes * 90
    for market_id, observations in quoteable_observations_by_market.items():
        ordered = sorted(observations, key=lambda item: item[0])
        current_start: datetime | None = None
        current_end: datetime | None = None
        current_samples: list[QuoteableMarketObservation] = []
        previous_ts: datetime | None = None

        def flush_window() -> None:
            nonlocal current_start, current_end, current_samples
            if current_start is None or current_end is None or not current_samples:
                return
            windows.append(
                {
                    "market_id": market_id,
                    "title": market_titles.get(market_id, market_id),
                    "start": current_start.isoformat().replace("+00:00", "Z"),
                    "end": current_end.isoformat().replace("+00:00", "Z"),
                    "sample_count": len(current_samples),
                    "quoteable_minutes": len(current_samples) * interval_minutes,
                    "median_normalized_spread_bps": round(
                        median(
                            [
                                float(item.best_normalized_spread_bps)
                                for item in current_samples
                                if item.best_normalized_spread_bps is not None
                            ]
                        ),
                        6,
                    )
                    if any(item.best_normalized_spread_bps is not None for item in current_samples)
                    else None,
                    "median_depth_notional": round(median([float(item.best_top_depth_notional) for item in current_samples]), 6),
                }
            )

        for observed_at, observation in ordered:
            if previous_ts is None or (observed_at - previous_ts).total_seconds() <= max_gap_seconds:
                if current_start is None:
                    current_start = observed_at
                current_end = observed_at
                current_samples.append(observation)
            else:
                flush_window()
                current_start = observed_at
                current_end = observed_at
                current_samples = [observation]
            previous_ts = observed_at
        flush_window()

    windows.sort(key=lambda item: (-float(item["quoteable_minutes"]), item["market_id"], item["start"]))
    best_markets = sorted(
        (
            {
                "market_id": market_id,
                "title": market_titles.get(market_id, market_id),
                "quoteable_minutes": minutes,
                "quoteable_samples": int(minutes / interval_minutes),
            }
            for market_id, minutes in quoteable_minutes_by_market.items()
        ),
        key=lambda item: (-float(item["quoteable_minutes"]), item["market_id"]),
    )
    best_hours = sorted(
        (
            {
                "hour_utc": hour,
                "quoteable_samples": count,
                "quoteable_minutes": count * interval_minutes,
            }
            for hour, count in hour_counts.items()
        ),
        key=lambda item: (-int(item["quoteable_samples"]), int(item["hour_utc"])),
    )
    best_dayparts = sorted(
        (
            {
                "daypart_utc": label,
                "quoteable_samples": count,
                "quoteable_minutes": count * interval_minutes,
            }
            for label, count in daypart_counts.items()
        ),
        key=lambda item: (-int(item["quoteable_samples"]), str(item["daypart_utc"])),
    )
    quoteable_ratio = round((total_quoteable_observations / total_observations), 6) if total_observations else 0.0

    if total_quoteable_observations == 0:
        conclusion_hint = "structurally_unquoteable_so_far"
    elif len(best_markets) <= 2:
        conclusion_hint = "narrow_subset_quoteable"
    else:
        conclusion_hint = "recurring_quoteable_windows_found"

    return QuoteableWindowSummary(
        generated_at=_utc_now_z(),
        sample_count=len(samples),
        interval_minutes=interval_minutes,
        markets_seen=len(markets_seen),
        markets_checked=total_observations,
        quoteable_count=total_quoteable_observations,
        quoteable_ratio=quoteable_ratio,
        quoteable_minutes_by_market=dict(sorted(quoteable_minutes_by_market.items())),
        quoteable_windows=windows[:50],
        reason_counts=dict(sorted(reason_counts.items())),
        best_markets_by_quoteable_time=best_markets[:20],
        best_hours_utc=best_hours,
        best_dayparts_utc=best_dayparts,
        median_normalized_spread_bps_when_quoteable=round(median(quoteable_spreads), 6) if quoteable_spreads else None,
        median_depth_when_quoteable=round(median(quoteable_depths), 6) if quoteable_depths else None,
        median_depth_shares_when_quoteable=round(median(quoteable_depth_shares), 6) if quoteable_depth_shares else None,
        latest_sample={
            "sample_id": samples[-1].sample_id,
            "sampled_at": samples[-1].sampled_at,
            "quoteable_count": samples[-1].quoteable_count,
            "quoteable_ratio": samples[-1].quoteable_ratio,
            "fetched_market_states": samples[-1].fetched_market_states,
        },
        conclusion_hint=conclusion_hint,
    )


def write_quoteable_summary(path: str | Path, summary: QuoteableWindowSummary) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary.model_dump(mode="json"), indent=2), encoding="utf-8")
    return output


def write_quoteable_summary_markdown(path: str | Path, summary: QuoteableWindowSummary) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Quoteable Window Monitor",
        "",
        f"- Generated at: `{summary.generated_at}`",
        f"- Samples: `{summary.sample_count}`",
        f"- Interval minutes: `{summary.interval_minutes}`",
        f"- Markets seen: `{summary.markets_seen}`",
        f"- Markets checked: `{summary.markets_checked}`",
        f"- Quoteable observations: `{summary.quoteable_count}`",
        f"- Quoteable ratio: `{summary.quoteable_ratio}`",
        f"- Conclusion hint: `{summary.conclusion_hint}`",
        "",
        "## Best Markets",
    ]
    if summary.best_markets_by_quoteable_time:
        for item in summary.best_markets_by_quoteable_time[:10]:
            lines.append(
                f"- `{item['market_id']}` {item['title']}: `{item['quoteable_minutes']}` quoteable minutes"
            )
    else:
        lines.append("- No quoteable markets yet.")
    lines.extend(["", "## Best Hours UTC"])
    if summary.best_hours_utc:
        for item in summary.best_hours_utc[:8]:
            lines.append(
                f"- `{int(item['hour_utc']):02d}:00` UTC: `{item['quoteable_minutes']}` quoteable minutes"
            )
    else:
        lines.append("- No quoteable hours yet.")
    lines.extend(["", "## Dominant Rejection Reasons"])
    if summary.reason_counts:
        for reason, count in list(summary.reason_counts.items())[:10]:
            lines.append(f"- `{reason}`: `{count}`")
    else:
        lines.append("- No rejection reasons recorded.")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def run_quoteable_window_monitor(
    records: list[MarketRecord],
    *,
    settings: Settings,
    config: ShadowAConfig,
    selection_mode: str = "broad",
    strict_market_ids: set[str] | None = None,
    provider: MarketStateProvider | None = None,
    samples_path: str | Path = REPORTS_ROOT / "quoteable_window_monitor_samples.jsonl",
    summary_path: str | Path = REPORTS_ROOT / "quoteable_window_monitor_latest.json",
    markdown_path: str | Path = REPORTS_ROOT / "quoteable_window_monitor_latest.md",
    iterations: int = 1,
    sleep_seconds: int = 300,
) -> QuoteableWindowSummary:
    run_id = f"quoteable-window-monitor-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    set_run_context(RunContext(environment=settings.environment, run_id=run_id))
    emit_event(
        "quoteable_window_monitor_started",
        payload={
            "input_markets": len(records),
            "selection_mode": selection_mode,
            "iterations": iterations,
            "sleep_seconds": sleep_seconds,
        },
    )
    loops = iterations if iterations > 0 else None
    completed = 0
    latest_summary: QuoteableWindowSummary | None = None
    while loops is None or completed < loops:
        sample = sample_quoteable_window(
            records,
            settings=settings,
            config=config,
            selection_mode=selection_mode,
            strict_market_ids=strict_market_ids,
            provider=provider,
        )
        append_quoteable_sample(samples_path, sample)
        summary = summarize_quoteable_samples(load_quoteable_samples(samples_path))
        write_quoteable_summary(summary_path, summary)
        write_quoteable_summary_markdown(markdown_path, summary)
        latest_summary = summary
        emit_event(
            "quoteable_window_monitor_sampled",
            payload={
                "sample_id": sample.sample_id,
                "quoteable_count": sample.quoteable_count,
                "fetched_market_states": sample.fetched_market_states,
                "summary_path": str(summary_path),
            },
        )
        completed += 1
        if loops is not None and completed >= loops:
            break
        time.sleep(max(sleep_seconds, 1))

    latest_summary = latest_summary or summarize_quoteable_samples([])
    emit_event(
        "quoteable_window_monitor_completed",
        payload={
            "sample_count": latest_summary.sample_count,
            "quoteable_ratio": latest_summary.quoteable_ratio,
            "conclusion_hint": latest_summary.conclusion_hint,
            "summary_path": str(summary_path),
        },
    )
    return latest_summary
