from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.common.paths import RUNTIME_ROOT


EVENTS_PATH = RUNTIME_ROOT / "runtime_events.jsonl"
SCHEMA_VERSION = "polymarket_lifecycle_v1"


@dataclass
class RunContext:
    repo: str = "polymarket-bot"
    environment: str = "research"
    run_id: str = ""
    strategy_id: str = "polymarket_mm_v1"
    family: str = "polymarket_mm_v1"
    variant_id: str | None = "reward_aware_passive_v1"
    profile_id: str | None = None
    schema_version: str = SCHEMA_VERSION


_CURRENT_CONTEXT = RunContext()


def set_run_context(context: RunContext) -> None:
    global _CURRENT_CONTEXT
    _CURRENT_CONTEXT = context


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _caller_source() -> tuple[str | None, int | None]:
    this_file = Path(__file__).resolve()
    for frame in inspect.stack()[2:]:
        try:
            candidate = Path(frame.filename).resolve()
        except OSError:
            continue
        if candidate != this_file:
            return str(candidate), int(frame.lineno)
    return None, None


def _stable_hash(parts: list[Any]) -> str:
    raw = json.dumps(parts, ensure_ascii=True, separators=(",", ":"), sort_keys=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def emit_event(event_type: str, *, market_id: str | None = None, payload: dict[str, Any] | None = None, ts: str | None = None) -> dict[str, Any]:
    event_ts = ts or _utc_now()
    source_file, source_line = _caller_source()
    idem = _stable_hash([event_type, _CURRENT_CONTEXT.repo, _CURRENT_CONTEXT.run_id, market_id or "", event_ts])
    record = {
        "schema_version": SCHEMA_VERSION,
        "event_id": f"evt_{idem[:24]}",
        "idempotency_key": idem,
        "event_type": event_type,
        "repo": _CURRENT_CONTEXT.repo,
        "environment": _CURRENT_CONTEXT.environment,
        "strategy_id": _CURRENT_CONTEXT.strategy_id,
        "family": _CURRENT_CONTEXT.family,
        "variant_id": _CURRENT_CONTEXT.variant_id,
        "run_id": _CURRENT_CONTEXT.run_id,
        "market_id": market_id,
        "ts": event_ts,
        "source_file": source_file,
        "source_line": source_line,
        "payload": dict(payload or {}),
    }
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=True) + "\n")
    return record

