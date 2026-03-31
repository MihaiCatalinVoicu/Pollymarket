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

    def _pull_paginated(
        self,
        fetch_page,
        *,
        total_limit: int,
        active: bool | None,
        closed: bool | None,
        page_size: int,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        offset = 0
        requested_page_size = max(1, page_size)
        while len(items) < total_limit:
            current_page_size = min(requested_page_size, total_limit - len(items))
            batch = fetch_page(limit=current_page_size, offset=offset, active=active, closed=closed)
            if not batch:
                break
            items.extend(batch)
            if len(batch) < current_page_size:
                break
            offset += len(batch)
        return items

    def pull(
        self,
        *,
        market_limit: int = 100,
        event_limit: int = 100,
        active: bool | None = True,
        closed: bool | None = False,
        page_size: int = 200,
    ) -> DiscoveryBatch:
        return DiscoveryBatch(
            markets=self._pull_paginated(
                self.client.get_markets,
                total_limit=market_limit,
                active=active,
                closed=closed,
                page_size=page_size,
            ),
            events=self._pull_paginated(
                self.client.get_events,
                total_limit=event_limit,
                active=active,
                closed=closed,
                page_size=page_size,
            ),
        )
