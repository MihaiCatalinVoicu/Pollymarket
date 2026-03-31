from __future__ import annotations

from src.discovery.service import DiscoveryService


class _FakeClient:
    def __init__(self) -> None:
        self.market_calls: list[tuple[int, int]] = []
        self.event_calls: list[tuple[int, int]] = []

    def get_markets(self, *, limit: int, offset: int, active=None, closed=None):
        self.market_calls.append((limit, offset))
        items = [{"id": f"m-{index}"} for index in range(offset, min(offset + limit, 450))]
        return items

    def get_events(self, *, limit: int, offset: int, active=None, closed=None):
        self.event_calls.append((limit, offset))
        items = [{"id": f"e-{index}"} for index in range(offset, min(offset + limit, 260))]
        return items


def test_pull_paginates_until_requested_limit() -> None:
    client = _FakeClient()
    service = DiscoveryService(client)

    batch = service.pull(market_limit=425, event_limit=225, page_size=100)

    assert len(batch.markets) == 425
    assert len(batch.events) == 225
    assert client.market_calls == [(100, 0), (100, 100), (100, 200), (100, 300), (25, 400)]
    assert client.event_calls == [(100, 0), (100, 100), (25, 200)]
