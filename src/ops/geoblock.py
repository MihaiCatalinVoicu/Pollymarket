from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


GEOBLOCK_ENDPOINT = "https://polymarket.com/api/geoblock"


@dataclass
class GeoblockStatus:
    blocked: bool
    ip: str | None
    country: str | None
    region: str | None
    checked_at: str
    raw: dict[str, Any]

    @property
    def geoblock_ok(self) -> bool:
        return not self.blocked


def check_geoblock(endpoint: str = GEOBLOCK_ENDPOINT, timeout_seconds: int = 15) -> GeoblockStatus:
    response = requests.get(endpoint, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    return GeoblockStatus(
        blocked=bool(payload.get("blocked", False)),
        ip=payload.get("ip"),
        country=payload.get("country"),
        region=payload.get("region"),
        checked_at=datetime.now(timezone.utc).isoformat(),
        raw=payload,
    )


def write_geoblock_status(path: str | Path, status: GeoblockStatus) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(status), indent=2), encoding="utf-8")
    return output
