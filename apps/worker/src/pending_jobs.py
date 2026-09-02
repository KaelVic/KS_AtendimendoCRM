from __future__ import annotations

from collections.abc import Awaitable, Callable


class PendingNotificationJob:
    """Worker-side boundary for the PostgreSQL-backed reminder dispatcher."""

    def __init__(self, dispatch_once: Callable[[], Awaitable[object]]) -> None:
        self.dispatch_once = dispatch_once

    async def run_once(self) -> object:
        return await self.dispatch_once()
