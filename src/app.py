from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import typer

from src.common.paths import REGISTRY_ROOT, RUN_MANIFEST_ROOT, RUNTIME_ROOT, ensure_data_roots
from src.config import load_json, load_settings
from src.discovery.client import GammaDiscoveryClient
from src.discovery.service import DiscoveryService
from src.execution.heartbeat import HeartbeatGuard
from src.ops.geoblock import check_geoblock, write_geoblock_status
from src.ops.run_manifest import build_run_manifest, write_run_manifest
from src.ops.runtime_event_logger import emit_event
from src.registry.filtering import UniverseFilterPolicy
from src.registry.models import MarketRecord
from src.registry.service import build_registry_snapshot, filter_registry, write_eligibility, write_snapshot
from src.storage.db import ensure_schema


app = typer.Typer(help="Polymarket MM V1 lane CLI.")


@app.command("fetch-markets")
def fetch_markets(limit: int = 50, output: Path = REGISTRY_ROOT / "raw_markets.json") -> None:
    settings = load_settings()
    ensure_data_roots()
    service = DiscoveryService(GammaDiscoveryClient(settings.gamma_api_url))
    batch = service.pull(market_limit=limit, event_limit=min(limit, 50), active=True)
    payload = {"markets": batch.markets, "events": batch.events}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    typer.echo(str(output))


@app.command("build-registry")
def build_registry(raw: Path = REGISTRY_ROOT / "raw_markets.json", output: Path = REGISTRY_ROOT / "market_registry_snapshot.json") -> None:
    payload = json.loads(raw.read_text(encoding="utf-8"))
    markets = payload["markets"] if isinstance(payload, dict) and "markets" in payload else payload
    records = build_registry_snapshot(markets)
    typer.echo(str(write_snapshot(output, records)))


@app.command("filter-eligible")
def filter_eligible(
    snapshot: Path = REGISTRY_ROOT / "market_registry_snapshot.json",
    output: Path = REGISTRY_ROOT / "eligible_markets_latest.json",
    allowlist: Path = Path("configs/market_allowlist.yaml"),
    denylist: Path = Path("configs/market_denylist.yaml"),
) -> None:
    records = [MarketRecord.model_validate(item) for item in json.loads(snapshot.read_text(encoding="utf-8"))]
    policy = UniverseFilterPolicy.from_yaml(str(allowlist), str(denylist))
    decisions = filter_registry(records, policy, as_of=date.today())
    typer.echo(str(write_eligibility(output, decisions)))


@app.command("emit-run-manifest")
def emit_run_manifest(
    metrics: Path,
    output: Path = RUN_MANIFEST_ROOT / "sample_run_manifest_v1.json",
    evaluation_phase: str = "research",
    run_type: str = "runtime_review",
    status: str = "completed",
    outcome_hint: str = "expand_oos",
) -> None:
    payload = load_json(metrics)
    manifest = build_run_manifest(
        source_run_id=payload.get("source_run_id", "polymarket-manual-run"),
        strategy_id=payload.get("strategy_id", "polymarket_mm_v1"),
        family_id=payload.get("family_id", "polymarket_mm_v1"),
        variant_id=payload.get("variant_id", "reward_aware_passive_v1"),
        run_type=run_type,
        evaluation_phase=evaluation_phase,
        status=status,
        outcome_hint=outcome_hint,
        metrics_summary=payload,
        artifact_links=payload.get("artifact_links") or [],
        next_phase_hint=payload.get("next_phase_hint"),
        parity_flags=payload.get("parity_flags") or [],
        requires_action=bool(payload.get("requires_action", False)),
    )
    typer.echo(str(write_run_manifest(output, manifest)))


@app.command("init-db")
def init_db() -> None:
    settings = load_settings()
    ensure_schema(settings.database_url)
    typer.echo("schema-ready")


@app.command("check-geoblock")
def check_geoblock_command(output: Path = RUNTIME_ROOT / "geoblock_check.json") -> None:
    ensure_data_roots()
    status = check_geoblock()
    typer.echo(str(write_geoblock_status(output, status)))


@app.command("venue-smoke")
def venue_smoke_command(
    output: Path = RUNTIME_ROOT / "venue_smoke.json",
    allow_create_api_key: bool = False,
    allow_live_orders: bool = False,
    allow_live_inventory_ops: bool = False,
) -> None:
    from src.ops.venue_smoke import run_venue_smoke, write_venue_smoke_report

    ensure_data_roots()
    settings = load_settings()
    report = run_venue_smoke(
        settings,
        allow_create_api_key=allow_create_api_key,
        allow_live_orders=allow_live_orders,
        allow_live_inventory_ops=allow_live_inventory_ops,
    )
    typer.echo(str(write_venue_smoke_report(output, report)))


@app.command("run-discovery")
def run_discovery() -> None:
    fetch_markets()


@app.command("run-book-listener")
def run_book_listener() -> None:
    emit_event("book_listener_started", payload={"service": "pm-book-listener"})
    typer.echo("book-listener-ready")


@app.command("run-strategy-mm")
def run_strategy_mm() -> None:
    emit_event("strategy_mm_started", payload={"service": "pm-strategy-mm"})
    typer.echo("strategy-mm-ready")


@app.command("run-order-router")
def run_order_router() -> None:
    emit_event("order_router_started", payload={"service": "pm-order-router"})
    typer.echo("order-router-ready")


@app.command("run-heartbeat")
def run_heartbeat() -> None:
    settings = load_settings()
    guard = HeartbeatGuard(
        interval_seconds=settings.heartbeat_interval_seconds,
        stale_seconds=settings.heartbeat_stale_seconds,
        buffer_seconds=settings.heartbeat_buffer_seconds,
    )
    guard.mark_sent()
    heartbeat_path = RUNTIME_ROOT / "heartbeat.json"
    heartbeat_path.write_text(json.dumps({"last_sent": True, "stale": guard.is_stale()}), encoding="utf-8")
    emit_event("heartbeat_sent", payload={"service": "pm-heartbeat"})
    typer.echo(str(heartbeat_path))


@app.command("run-inventory")
def run_inventory() -> None:
    emit_event("inventory_manager_started", payload={"service": "pm-inventory"})
    typer.echo("inventory-ready")


@app.command("run-settlement")
def run_settlement() -> None:
    emit_event("settlement_worker_started", payload={"service": "pm-settlement"})
    typer.echo("settlement-ready")


@app.command("write-daily-report")
def write_daily_report(output: Path = RUNTIME_ROOT.parent / "reports" / "daily_report.json") -> None:
    report = {
        "strategy_id": "polymarket_mm_v1",
        "status": "stub",
        "notes": "Replace with daily PnL, reward, heartbeat, and reconciliation aggregation.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    typer.echo(str(output))


if __name__ == "__main__":
    app()
