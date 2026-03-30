from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator

from pydantic import BaseModel


class BestBidAsk(BaseModel):
    market: str
    asset_id: str
    best_bid: float | None = None
    best_ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None


@dataclass
class MarketChannelSubscription:
    asset_ids: list[str]
    custom_feature_enabled: bool = True

    def to_payload(self) -> dict[str, Any]:
        return {
            "type": "market",
            "assets_ids": self.asset_ids,
            "custom_feature_enabled": self.custom_feature_enabled,
        }


class MarketWebsocketClient:
    def __init__(self, url: str) -> None:
        self.url = url

    async def listen(self, subscription: MarketChannelSubscription) -> AsyncIterator[dict[str, Any]]:
        import websockets

        async with websockets.connect(self.url) as socket:
            await socket.send(json.dumps(subscription.to_payload()))
            async for raw in socket:
                yield json.loads(raw)

