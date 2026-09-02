from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .dependencies import get_db_session, require_owner
from ..calendar.adapter import CalendarNotConfigured
from ..calendar.contracts import (
    AvailabilityResponse,
    MeetingCreateRequest,
    MeetingResponse,
    NoShowResponse,
)
from ..calendar.fake import FakeCalendarAdapter
from ..calendar.service import (
    InMemoryCalendarLock,
    MeetingConflict,
    MeetingError,
    MeetingIdempotencyConflict,
    MeetingNotFound,
    MeetingOutsideBusinessHours,
    MeetingService,
)
from ..core.config import get_settings
from ..db.models import Meeting, User
from ..services.auth import AuthenticatedOwner

router = APIRouter(prefix="/meetings", tags=["Meetings"])
_fake_calendar = FakeCalendarAdapter()
_calendar_lock = InMemoryCalendarLock()


def _calendar() -> FakeCalendarAdapter:
    # The real Google adapter is deliberately not enabled without a configured
    # credential adapter; the public API never receives credentials.
    if get_settings().CALENDAR_PROVIDER.lower() != "fake":
        raise CalendarNotConfigured("Calendar provider não configurado nesta implantação")
    return _fake_calendar


def _service(session: AsyncSession) -> MeetingService:
    settings = get_settings()
    return MeetingService(
        session,
        _calendar(),
        _calendar_lock,
        personal_calendar_id=settings.CALENDAR_PERSONAL_ID,
        onboarding_calendar_id=settings.CALENDAR_ONBOARDING_ID,
    )


def _response(meeting: Meeting, duplicate: bool = False) -> MeetingResponse:
    return MeetingResponse(
        id=meeting.id,
        tenant_id=meeting.tenant_id,
        conversation_id=meeting.conversation_id,
        starts_at=meeting.starts_at,
        ends_at=meeting.ends_at,
        timezone=meeting.timezone,
        status=meeting.status,
        reminder_kind=meeting.reminder_kind,
        reminder_due_at=meeting.reminder_due_at,
        rematch_allowed=meeting.status == "NO_SHOW",
        duplicate=duplicate,
    )


@router.get("/availability", response_model=AvailabilityResponse)
async def get_availability(
    day: date = Query(...),
    now: datetime | None = Query(default=None),
    owner: AuthenticatedOwner = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> AvailabilityResponse:
    try:
        slots = await _service(session).availability(owner.tenant_id, day, now=now)
    except CalendarNotConfigured as exc:
        raise HTTPException(
            status_code=503, detail={"error_code": "CALENDAR_NOT_CONFIGURED", "message": str(exc)}
        ) from exc
    return AvailabilityResponse(timezone="America/Sao_Paulo", slots=slots)


@router.post("", response_model=MeetingResponse, status_code=status.HTTP_201_CREATED)
async def reserve_meeting(
    payload: MeetingCreateRequest,
    request: Request,
    owner: AuthenticatedOwner = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> MeetingResponse:
    try:
        meeting, duplicate = await _service(session).reserve(
            owner.tenant_id,
            payload.conversation_id,
            payload.starts_at,
            payload.idempotency_key,
            correlation_id=request.state.correlation_id,
        )
    except MeetingNotFound as exc:
        raise HTTPException(
            status_code=404, detail={"error_code": str(exc), "message": "Conversa não encontrada"}
        ) from exc
    except MeetingOutsideBusinessHours as exc:
        raise HTTPException(
            status_code=422,
            detail={"error_code": "MEETING_OUTSIDE_BUSINESS_HOURS", "message": str(exc)},
        ) from exc
    except (MeetingConflict, MeetingIdempotencyConflict) as exc:
        raise HTTPException(
            status_code=409, detail={"error_code": str(exc), "message": "Horário indisponível"}
        ) from exc
    except CalendarNotConfigured as exc:
        raise HTTPException(
            status_code=503, detail={"error_code": "CALENDAR_NOT_CONFIGURED", "message": str(exc)}
        ) from exc
    return _response(meeting, duplicate)


@router.post("/{meeting_id}/no-show", response_model=NoShowResponse)
async def mark_no_show(
    meeting_id: UUID,
    request: Request,
    owner: AuthenticatedOwner = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> NoShowResponse:
    actor_user_id = await session.scalar(
        select(User.id).where(User.tenant_id == owner.tenant_id, User.email == owner.email)
    )
    if actor_user_id is None:
        raise HTTPException(
            status_code=403,
            detail={"error_code": "OWNER_NOT_FOUND", "message": "Operador não encontrado"},
        )
    try:
        meeting = await _service(session).mark_no_show(
            owner.tenant_id,
            meeting_id,
            correlation_id=request.state.correlation_id,
            actor_user_id=actor_user_id,
        )
    except MeetingNotFound as exc:
        raise HTTPException(
            status_code=404, detail={"error_code": str(exc), "message": "Reunião não encontrada"}
        ) from exc
    except MeetingError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error_code": str(exc), "message": "No-show não pode ser marcado"},
        ) from exc
    return NoShowResponse(meeting_id=meeting.id, status=meeting.status, rematch_allowed=True)
