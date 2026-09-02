from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class TransientCalendarError(RuntimeError):
    pass


class CalendarNotConfigured(RuntimeError):
    pass


@dataclass(frozen=True)
class CalendarEvent:
    external_event_id: str
    calendar_id: str
    starts_at: datetime
    ends_at: datetime
    title: str = ""


class CalendarAdapter(Protocol):
    async def list_events(
        self, calendar_id: str, starts_at: datetime, ends_at: datetime
    ) -> list[CalendarEvent]: ...

    async def create_event(
        self,
        calendar_id: str,
        event: CalendarEvent,
        idempotency_key: str,
    ) -> CalendarEvent: ...


class GoogleCalendarAdapter:
    """Port placeholder; real credentials are intentionally never in code."""

    def __init__(self, credentials_json: str | None):
        self.configured = bool(credentials_json)

    async def list_events(
        self, calendar_id: str, starts_at: datetime, ends_at: datetime
    ) -> list[CalendarEvent]:
        del calendar_id, starts_at, ends_at
        raise CalendarNotConfigured("Google Calendar não configurado")

    async def create_event(
        self, calendar_id: str, event: CalendarEvent, idempotency_key: str
    ) -> CalendarEvent:
        del calendar_id, event, idempotency_key
        raise CalendarNotConfigured("Google Calendar não configurado")
