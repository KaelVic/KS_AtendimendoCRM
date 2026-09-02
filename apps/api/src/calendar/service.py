from __future__ import annotations

import asyncio
from time import perf_counter
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, AsyncContextManager, Protocol
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import AuditEvent, Conversation, Meeting, MeetingReminder
from .adapter import CalendarAdapter, CalendarEvent, TransientCalendarError
from ..core.observability import record_integration

BUSINESS_TIMEZONE = ZoneInfo("America/Sao_Paulo")
PERSONAL_CALENDAR_ID = "personal"
ONBOARDING_CALENDAR_ID = "Onboarding KaelSolutions"
MEETING_DURATION = timedelta(minutes=45)


class MeetingError(ValueError):
    pass


class MeetingConflict(MeetingError):
    pass


class MeetingIdempotencyConflict(MeetingError):
    pass


class MeetingOutsideBusinessHours(MeetingError):
    pass


class MeetingNotFound(LookupError):
    pass


class CalendarLock(Protocol):
    def hold(self, tenant_id: UUID) -> AsyncContextManager[None]: ...


class InMemoryCalendarLock:
    def __init__(self):
        self._locks: dict[UUID, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    @asynccontextmanager
    async def hold(self, tenant_id: UUID):
        async with self._guard:
            lock = self._locks.setdefault(tenant_id, asyncio.Lock())
        async with lock:
            yield


class RedisCalendarLock:
    def __init__(self, redis: Any, timeout_seconds: int = 60):
        self.redis = redis
        self.timeout_seconds = timeout_seconds

    @asynccontextmanager
    async def hold(self, tenant_id: UUID):
        lock = self.redis.lock(
            f"ks:calendar:{tenant_id}",
            timeout=self.timeout_seconds,
            blocking_timeout=self.timeout_seconds,
        )
        if not await lock.acquire():
            raise MeetingConflict("agenda ocupada; tente novamente")
        try:
            yield
        finally:
            await lock.release()


@dataclass(frozen=True)
class ReminderPlan:
    kind: str
    due_at: datetime


def reminder_plan(starts_at: datetime, confirmed_at: datetime) -> ReminderPlan | None:
    starts_utc = starts_at.astimezone(timezone.utc)
    confirmed_utc = confirmed_at.astimezone(timezone.utc)
    until_start = starts_utc - confirmed_utc
    if until_start >= timedelta(hours=2):
        return ReminderPlan("2H", starts_utc - timedelta(hours=2))
    if until_start >= timedelta(minutes=90):
        return ReminderPlan("90M", starts_utc - timedelta(minutes=90))
    return None


def _valid_local_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise MeetingOutsideBusinessHours("horário deve conter fuso")
    local = value.astimezone(BUSINESS_TIMEZONE)
    naive = local.replace(tzinfo=None)
    if naive != local.astimezone(timezone.utc).astimezone(BUSINESS_TIMEZONE).replace(tzinfo=None):
        raise MeetingOutsideBusinessHours("horário inexistente no fuso local")
    return local


def _within_business_hours(starts_at: datetime) -> bool:
    local = _valid_local_datetime(starts_at)
    end = local + MEETING_DURATION
    return (
        time(9, 0) <= local.time() <= time(17, 0)
        and end.date() == local.date()
        and end.time() <= time(18, 0)
    )


class MeetingService:
    def __init__(
        self,
        session: AsyncSession,
        calendar: CalendarAdapter,
        lock: CalendarLock,
        *,
        personal_calendar_id: str = PERSONAL_CALENDAR_ID,
        onboarding_calendar_id: str = ONBOARDING_CALENDAR_ID,
    ):
        self.session = session
        self.calendar = calendar
        self.lock = lock
        self.personal_calendar_id = personal_calendar_id
        self.onboarding_calendar_id = onboarding_calendar_id

    async def availability(
        self, tenant_id: UUID, day: date, *, now: datetime | None = None
    ) -> list[datetime]:
        local_start = datetime.combine(day, time(9), BUSINESS_TIMEZONE)
        local_end = datetime.combine(day, time(18), BUSINESS_TIMEZONE)
        start_utc = local_start.astimezone(timezone.utc)
        end_utc = local_end.astimezone(timezone.utc)
        busy = await self._busy(start_utc, end_utc)
        current_local = now.astimezone(BUSINESS_TIMEZONE) if now else None
        slots: list[datetime] = []
        cursor = local_start
        while cursor.time() <= time(17, 0):
            candidate_end = cursor + MEETING_DURATION
            if (current_local is None or cursor > current_local) and not any(
                event.starts_at < candidate_end.astimezone(timezone.utc)
                and event.ends_at > cursor.astimezone(timezone.utc)
                for event in busy
            ):
                slots.append(cursor)
            cursor += timedelta(minutes=30)
        return slots

    async def reserve(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        starts_at: datetime,
        idempotency_key: str,
        *,
        correlation_id: str,
        now: datetime | None = None,
        actor_user_id: UUID | None = None,
    ) -> tuple[Meeting, bool]:
        if not _within_business_hours(starts_at):
            raise MeetingOutsideBusinessHours("reunião fora de 09:00–18:00 ou início após 17:00")
        starts_local = _valid_local_datetime(starts_at)
        starts_utc = starts_local.astimezone(timezone.utc)
        ends_utc = (starts_local + MEETING_DURATION).astimezone(timezone.utc)
        existing = await self.session.scalar(
            select(Meeting).where(
                Meeting.tenant_id == tenant_id, Meeting.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            if existing.starts_at != starts_utc or existing.conversation_id != conversation_id:
                raise MeetingIdempotencyConflict("MEETING_KEY_REUSED_WITH_DIFFERENT_SLOT")
            return existing, True

        conversation = await self.session.scalar(
            select(Conversation).where(
                Conversation.tenant_id == tenant_id, Conversation.id == conversation_id
            )
        )
        if conversation is None:
            raise MeetingNotFound("CONVERSATION_NOT_FOUND")

        async with self.lock.hold(tenant_id):
            # Re-read both the CRM reservation and external calendars after lock.
            existing = await self.session.scalar(
                select(Meeting).where(
                    Meeting.tenant_id == tenant_id, Meeting.idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                return existing, True
            if await self._has_conflict(starts_utc, ends_utc):
                raise MeetingConflict("MEETING_SLOT_UNAVAILABLE")

            event = CalendarEvent(
                external_event_id=idempotency_key,
                calendar_id=self.onboarding_calendar_id,
                starts_at=starts_utc,
                ends_at=ends_utc,
                title="Reunião KaelSolutions",
            )
            created_event = await self._create_with_retry(
                self.onboarding_calendar_id, event, idempotency_key
            )
            confirmed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
            plan = reminder_plan(starts_utc, confirmed_at)
            meeting = Meeting(
                id=uuid4(),
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                idempotency_key=idempotency_key,
                provider="google-calendar",
                calendar_id=self.onboarding_calendar_id,
                external_event_id=created_event.external_event_id,
                starts_at=starts_utc,
                ends_at=ends_utc,
                timezone="America/Sao_Paulo",
                status="SCHEDULED",
                title="Reunião KaelSolutions",
                reminder_kind=plan.kind if plan else None,
                reminder_due_at=plan.due_at if plan else None,
                version=1,
                created_at=confirmed_at,
                updated_at=confirmed_at,
            )
            self.session.add(meeting)
            self.session.add(
                AuditEvent(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    action="MEETING_RESERVED",
                    target_type="meeting",
                    target_id=meeting.id,
                    correlation_id=correlation_id,
                    event_metadata={
                        "calendar": self.onboarding_calendar_id,
                        "reminder": plan.kind if plan else None,
                    },
                    created_at=confirmed_at,
                    updated_at=confirmed_at,
                )
            )
            if plan:
                self.session.add(
                    MeetingReminder(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        meeting_id=meeting.id,
                        kind=plan.kind,
                        idempotency_key=f"meeting:{meeting.id}:reminder:{plan.kind}",
                        due_at=plan.due_at,
                        status="PENDING",
                        attempts=0,
                        created_at=confirmed_at,
                        updated_at=confirmed_at,
                    )
                )
            try:
                await self.session.commit()
            except IntegrityError:
                await self.session.rollback()
                existing = await self.session.scalar(
                    select(Meeting).where(
                        Meeting.tenant_id == tenant_id, Meeting.idempotency_key == idempotency_key
                    )
                )
                if existing is None:
                    raise
                return existing, True
            await self.session.refresh(meeting)
            return meeting, False

    async def mark_no_show(
        self, tenant_id: UUID, meeting_id: UUID, *, correlation_id: str, actor_user_id: UUID
    ) -> Meeting:
        async with self.lock.hold(tenant_id):
            meeting = await self.session.scalar(
                select(Meeting).where(Meeting.tenant_id == tenant_id, Meeting.id == meeting_id)
            )
            if meeting is None:
                raise MeetingNotFound("MEETING_NOT_FOUND")
            if meeting.status != "SCHEDULED":
                raise MeetingError("MEETING_NOT_SCHEDULED")
            now = datetime.now(timezone.utc)
            changed = await self.session.execute(
                update(Meeting)
                .where(
                    Meeting.tenant_id == tenant_id,
                    Meeting.id == meeting_id,
                    Meeting.version == meeting.version,
                )
                .values(
                    status="NO_SHOW",
                    no_show_marked_at=now,
                    version=Meeting.version + 1,
                    updated_at=now,
                )
            )
            if getattr(changed, "rowcount", 0) != 1:
                await self.session.rollback()
                raise MeetingError("MEETING_CHANGED_CONCURRENTLY")
            meeting.status = "NO_SHOW"
            meeting.no_show_marked_at = now
            meeting.version += 1
            meeting.updated_at = now
            self.session.add(
                AuditEvent(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    action="MEETING_NO_SHOW_MARKED",
                    target_type="meeting",
                    target_id=meeting_id,
                    correlation_id=correlation_id,
                    event_metadata={},
                    created_at=now,
                    updated_at=now,
                )
            )
            await self.session.commit()
            return meeting

    async def _busy(self, starts_at: datetime, ends_at: datetime) -> list[CalendarEvent]:
        personal, onboarding = await asyncio.gather(
            self.calendar.list_events(self.personal_calendar_id, starts_at, ends_at),
            self.calendar.list_events(self.onboarding_calendar_id, starts_at, ends_at),
        )
        return personal + onboarding

    async def _has_conflict(self, starts_at: datetime, ends_at: datetime) -> bool:
        return bool(await self._busy(starts_at, ends_at))

    async def _create_with_retry(
        self, calendar_id: str, event: CalendarEvent, idempotency_key: str
    ) -> CalendarEvent:
        started = perf_counter()
        for attempt in range(2):
            try:
                created = await self.calendar.create_event(calendar_id, event, idempotency_key)
                record_integration("calendar", "success", (perf_counter() - started) * 1000)
                return created
            except TransientCalendarError:
                if attempt == 1:
                    record_integration("calendar", "error", (perf_counter() - started) * 1000)
                    raise
                await asyncio.sleep(0)
        raise AssertionError("unreachable")
