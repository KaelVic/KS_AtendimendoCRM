from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from uuid import UUID, uuid4


REMINDER_INTERVAL = timedelta(hours=2)


class PendingStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


@dataclass
class PendingItemData:
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    kind: str
    created_at: datetime
    due_at: datetime
    status: PendingStatus = PendingStatus.OPEN
    resolved_at: datetime | None = None


@dataclass(frozen=True)
class ClaimedNotification:
    pending_id: UUID
    window_index: int
    idempotency_key: str


def window_index(created_at: datetime, now: datetime) -> int:
    """Returns the elapsed two-hour window, with window zero being immediate."""
    elapsed = (now - created_at).total_seconds()
    return max(0, int(elapsed // REMINDER_INTERVAL.total_seconds()))


class PendingNotificationCoordinator:
    """Small deterministic core used by the SQL adapter and unit tests.

    PostgreSQL remains authoritative in production; this class models the
    invariants without requiring a database for fast tests.
    """

    def __init__(self) -> None:
        self._claims: set[tuple[UUID, int]] = set()
        self._lock = asyncio.Lock()

    def due_window(self, item: PendingItemData, now: datetime) -> int:
        if item.status is PendingStatus.RESOLVED or now < item.created_at:
            return -1
        return window_index(item.created_at, now)

    async def claim(self, item: PendingItemData, now: datetime) -> ClaimedNotification | None:
        async with self._lock:
            current_window = self.due_window(item, now)
            if current_window < 0:
                return None
            claim_key = (item.id, current_window)
            if claim_key in self._claims:
                return None
            self._claims.add(claim_key)
            return ClaimedNotification(
                pending_id=item.id,
                window_index=current_window,
                idempotency_key=f"pending:{item.id}:window:{current_window}",
            )

    async def resolve(self, item: PendingItemData, reason: str, now: datetime | None = None) -> None:
        if item.status is PendingStatus.RESOLVED:
            return
        item.status = PendingStatus.RESOLVED
        item.resolved_at = now or datetime.now(timezone.utc)

    def reopen(self, item: PendingItemData, now: datetime, activity_key: str) -> PendingItemData:
        if not activity_key.strip():
            raise ValueError("activity_key obrigatória")
        return replace(
            item,
            id=uuid4(),
            created_at=now,
            due_at=now,
            status=PendingStatus.OPEN,
            resolved_at=None,
        )
