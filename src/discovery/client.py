from __future__ import annotations

from typing import Any

from src.common.http_client import JsonHttpClient


class GammaDiscoveryClient:
    def __init__(self, base_url: str) -> None:
        self.http = JsonHttpClient(base_url)

    def get_markets(self, *, limit: int = 100, offset: int = 0, active: bool | None = None, closed: bool | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if active is not None:
            params["active"] = str(active).lower()
        if closed is not None:
            params["closed"] = str(closed).lower()
        payload = self.http.get("/markets", params=params)
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("markets", "data", "items"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        raise ValueError("unexpected Gamma markets payload")

    def get_events(self, *, limit: int = 100, offset: int = 0, active: bool | None = None, closed: bool | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if active is not None:
            params["active"] = str(active).lower()
        if closed is not None:
            params["closed"] = str(closed).lower()
        payload = self.http.get("/events", params=params)
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("events", "data", "items"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        raise ValueError("unexpected Gamma events payload")
