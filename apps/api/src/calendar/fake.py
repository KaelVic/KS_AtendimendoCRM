from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from .adapter import CalendarEvent, TransientCalendarError


class FakeCalendarAdapter:
    def __init__(self, fail_create_times: int = 0):
        self.events: dict[str, list[CalendarEvent]] = {}
        self.idempotent_events: dict[tuple[str, str], CalendarEvent] = {}
        self.fail_create_times = fail_create_times
        self.create_calls: list[str] = []
        self.on_list = None

    async def list_events(self, calendar_id: str, starts_at: datetime, ends_at: datetime):
        if self.on_list is not None:
            await self.on_list(calendar_id, starts_at, ends_at)
        return [
            event
            for event in self.events.get(calendar_id, [])
            if event.starts_at < ends_at and event.ends_at > starts_at
        ]

    async def create_event(self, calendar_id: str, event: CalendarEvent, idempotency_key: str):
        self.create_calls.append(idempotency_key)
        existing = self.idempotent_events.get((calendar_id, idempotency_key))
        if existing is not None:
            return existing
        if self.fail_create_times:
            self.fail_create_times -= 1
            raise TransientCalendarError("falha transitória simulada")
        created = CalendarEvent(
            external_event_id=str(uuid4()),
            calendar_id=calendar_id,
            starts_at=event.starts_at,
            ends_at=event.ends_at,
            title=event.title,
        )
        self.idempotent_events[(calendar_id, idempotency_key)] = created
        self.events.setdefault(calendar_id, []).append(created)
        return created

    def add_external_event(self, event: CalendarEvent) -> None:
        self.events.setdefault(event.calendar_id, []).append(event)
