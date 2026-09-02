from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID


class OutreachRateLimited(RuntimeError):
    pass


@dataclass
class ConservativeOutreachPolicy:
    daily_limit: int = 5
    minimum_interval: timedelta = timedelta(minutes=5)

    def __post_init__(self) -> None:
        self._sent: dict[UUID, deque[datetime]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def allow(self, tenant_id: UUID, now: datetime) -> None:
        async with self._lock:
            start = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            entries = self._sent[tenant_id]
            while entries and entries[0] < start:
                entries.popleft()
            if len(entries) >= self.daily_limit:
                raise OutreachRateLimited("OUTREACH_DAILY_LIMIT")
            if entries and now - entries[-1] < self.minimum_interval:
                raise OutreachRateLimited("OUTREACH_MINIMUM_INTERVAL")

    async def record(self, tenant_id: UUID, now: datetime) -> None:
        async with self._lock:
            self._sent[tenant_id].append(now)
