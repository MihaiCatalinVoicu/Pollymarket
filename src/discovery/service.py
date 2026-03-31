from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.discovery.client import GammaDiscoveryClient


@dataclass
class DiscoveryBatch:
    markets: list[dict[str, Any]]
    events: list[dict[str, Any]]


class DiscoveryService:
    def __init__(self, client: GammaDiscoveryClient) -> None:
        self.client = client

    def pull(self, *, market_limit: int = 100, event_limit: int = 100, active: bool | None = True, closed: bool | None = False) -> DiscoveryBatch:
        return DiscoveryBatch(
            markets=self.client.get_markets(limit=market_limit, active=active, closed=closed),
            events=self.client.get_events(limit=event_limit, active=active, closed=closed),
        )
