from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class JsonHttpClient:
    base_url: str
    timeout_seconds: int = 30

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self.session = requests.Session()

    def get(self, path: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Any:
        response = self.session.get(
            f"{self.base_url}/{path.lstrip('/')}",
            params=params,
            headers=headers,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def post(self, path: str, *, json_payload: dict[str, Any], headers: dict[str, str] | None = None) -> Any:
        response = self.session.post(
            f"{self.base_url}/{path.lstrip('/')}",
            json=json_payload,
            headers=headers,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

