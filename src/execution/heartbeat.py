from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class HeartbeatGuard:
    interval_seconds: int = 5
    stale_seconds: int = 10
    buffer_seconds: int = 5
    last_sent_at: datetime | None = None

    def mark_sent(self, sent_at: datetime | None = None) -> None:
        self.last_sent_at = sent_at or datetime.now(timezone.utc)

    def due(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        if self.last_sent_at is None:
            return True
        return now - self.last_sent_at >= timedelta(seconds=self.interval_seconds)

    def is_stale(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        if self.last_sent_at is None:
            return True
        return now - self.last_sent_at >= timedelta(seconds=self.stale_seconds + self.buffer_seconds)
