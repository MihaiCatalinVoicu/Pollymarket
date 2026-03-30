from __future__ import annotations

from typing import Any

from src.common.http_client import JsonHttpClient


class PriceHistoryClient:
    def __init__(self, base_url: str) -> None:
        self.http = JsonHttpClient(base_url)

    def fetch_history(self, *, market: str, interval: str = "1m", fidelity: int = 1) -> Any:
        return self.http.get(
            "/prices-history",
            params={"market": market, "interval": interval, "fidelity": fidelity},
        )

