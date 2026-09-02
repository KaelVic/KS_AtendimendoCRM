from __future__ import annotations

from datetime import timedelta
from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..db.session import async_session_factory
from ..db.models import OutreachDraft, User
from ..integrations.channel_router import ChannelRouter, SqlAlchemyRoutingBackend
from ..integrations.whatsapp import OpenWAWhatsAppAdapter, SessionStatus, SessionSnapshot
from ..outreach.contracts import (
    OutreachApproval,
    OutreachDraftCreate,
    OutreachDraftResponse,
    OutreachEdit,
    OutreachReject,
    OutreachSend,
)
from ..outreach.gateway import (
    ColdOutreachGateway,
    FakeColdOutreachGateway,
    WhatsAppColdOutreachGateway,
)
from ..outreach.policy import ConservativeOutreachPolicy
from ..outreach.service import (
    ApprovalExpired,
    OutreachAlreadySent,
    OutreachIdempotencyConflict,
    OutreachNotAllowed,
    OutreachNotFound,
    OutreachService,
    ResearchNotEligible,
)
from ..services.auth import AuthenticatedOwner
from .dependencies import get_db_session, require_owner

router = APIRouter(prefix="/outreach", tags=["Outreach approval"])
_settings = get_settings()
_policy = ConservativeOutreachPolicy(
    daily_limit=max(1, _settings.OUTREACH_DAILY_LIMIT),
    minimum_interval=timedelta(seconds=max(0, _settings.OUTREACH_MIN_INTERVAL_SECONDS)),
)


def _service(owner: AuthenticatedOwner, session: AsyncSession) -> OutreachService:
    settings = get_settings()
    gateway: ColdOutreachGateway
    if settings.OUTREACH_PROVIDER.lower() == "fake":
        gateway = FakeColdOutreachGateway(
            SessionSnapshot(
                tenant_id=owner.tenant_id,
                session_id="fake-outreach",
                owner_ref=owner.email,
                status=SessionStatus.CONNECTED,
                secure=True,
            )
        )
    elif settings.OUTREACH_PROVIDER.lower() == "openwa":
        if not settings.OPENWA_API_KEY or not settings.OPENWA_WEBHOOK_SECRET:
            raise HTTPException(
                status_code=503,
                detail={
                    "error_code": "OUTREACH_GATEWAY_NOT_CONFIGURED",
                    "message": "Gateway de prospecção não configurado",
                },
            )
        adapter = OpenWAWhatsAppAdapter(
                base_url=settings.OPENWA_SERVER_URL,
                api_key=settings.OPENWA_API_KEY,
                session_id=settings.OPENWA_SESSION_ID,
                tenant_id=owner.tenant_id,
                owner_ref=owner.email,
                webhook_secret=settings.OPENWA_WEBHOOK_SECRET,
        )
        gateway_id = UUID(settings.OPENWA_GATEWAY_ID)
        router = ChannelRouter(
            SqlAlchemyRoutingBackend(
                async_session_factory, lease_seconds=settings.OPENWA_LEASE_SECONDS
            ),
            {gateway_id: adapter},
            owner_id=settings.OPENWA_OWNER_ID,
            default_tenant_id=owner.tenant_id,
            default_session_id=settings.OPENWA_SESSION_ID,
        )
        gateway = WhatsAppColdOutreachGateway(router)
    else:
        raise HTTPException(
            status_code=503,
            detail={"error_code": "OUTREACH_PROVIDER_UNKNOWN", "message": "Provider não permitido"},
        )
    return OutreachService(
        session,
        gateway,
        approval_ttl=timedelta(hours=max(1, settings.OUTREACH_APPROVAL_TTL_HOURS)),
        policy=_policy,
    )


async def _actor_id(session: AsyncSession, owner: AuthenticatedOwner) -> UUID | None:
    return await session.scalar(
        select(User.id).where(User.tenant_id == owner.tenant_id, User.email == owner.email)
    )


def _response(row: OutreachDraft, duplicate: bool = False) -> OutreachDraftResponse:
    source_data = row.source_data or {}
    evidence_urls = [str(value) for value in source_data.get("evidence_urls", [])]
    return OutreachDraftResponse(
        id=row.id,
        tenant_id=row.tenant_id,
        research_id=row.research_id,
        company=row.company_name,
        source_url=row.source_url,
        evidence_urls=evidence_urls,
        findings=list(row.findings or [])[:3],
        contact=row.recipient_ref,
        draft_text=row.draft_text,
        approach_reason=row.approach_reason,
        status=cast(
            Literal[
                "PENDING_APPROVAL",
                "APPROVED",
                "REJECTED",
                "EXPIRED",
                "SENDING",
                "SENT",
                "PAUSED",
            ],
            row.status,
        ),
        expires_at=row.expires_at,
        approved_at=row.approved_at,
        sent_at=row.sent_at,
        provider_message_id=row.provider_message_id,
        pause_reason=row.pause_reason,
        duplicate=duplicate,
    )


def _raise(exc: Exception) -> HTTPException:
    if isinstance(exc, OutreachNotFound):
        return HTTPException(404, detail={"error_code": str(exc), "message": "Rascunho não encontrado"})
    if isinstance(exc, ResearchNotEligible):
        return HTTPException(422, detail={"error_code": str(exc), "message": "Pesquisa não revisável"})
    if isinstance(exc, (OutreachIdempotencyConflict, OutreachAlreadySent)):
        return HTTPException(409, detail={"error_code": str(exc), "message": "Operação duplicada ou conflitante"})
    if isinstance(exc, ApprovalExpired):
        return HTTPException(409, detail={"error_code": str(exc), "message": "A aprovação expirou"})
    return HTTPException(422, detail={"error_code": str(exc), "message": "Operação não permitida"})


@router.post("/drafts", response_model=OutreachDraftResponse, status_code=status.HTTP_201_CREATED)
async def create_draft(
    payload: OutreachDraftCreate,
    request: Request,
    owner: AuthenticatedOwner = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> OutreachDraftResponse:
    try:
        row, duplicate = await _service(owner, session).create(
            owner.tenant_id,
            payload,
            correlation_id=request.state.correlation_id,
            actor_user_id=await _actor_id(session, owner),
        )
    except (OutreachNotAllowed, ResearchNotEligible, OutreachIdempotencyConflict) as exc:
        raise _raise(exc) from exc
    return _response(row, duplicate)


@router.get("/drafts", response_model=list[OutreachDraftResponse])
async def list_drafts(
    status_filter: Literal[
        "PENDING_APPROVAL", "APPROVED", "REJECTED", "EXPIRED", "SENDING", "SENT", "PAUSED"
    ] | None = Query(default=None, alias="status"),
    owner: AuthenticatedOwner = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> list[OutreachDraftResponse]:
    statement = select(OutreachDraft).where(OutreachDraft.tenant_id == owner.tenant_id).order_by(OutreachDraft.created_at.desc())
    if status_filter:
        statement = statement.where(OutreachDraft.status == status_filter)
    rows = (await session.scalars(statement)).all()
    return [_response(row) for row in rows]


@router.put("/drafts/{draft_id}", response_model=OutreachDraftResponse)
async def edit_draft(
    draft_id: UUID,
    payload: OutreachEdit,
    request: Request,
    owner: AuthenticatedOwner = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> OutreachDraftResponse:
    try:
        row = await _service(owner, session).edit(
            owner.tenant_id,
            draft_id,
            payload,
            actor_user_id=await _actor_id(session, owner),
            correlation_id=request.state.correlation_id,
        )
    except (OutreachNotAllowed, OutreachNotFound) as exc:
        raise _raise(exc) from exc
    return _response(row)


@router.post("/drafts/{draft_id}/approve", response_model=OutreachDraftResponse)
async def approve_draft(
    draft_id: UUID,
    payload: OutreachApproval,
    request: Request,
    owner: AuthenticatedOwner = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> OutreachDraftResponse:
    try:
        row = await _service(owner, session).approve(
            owner.tenant_id,
            draft_id,
            confirmed=payload.confirmed,
            actor_user_id=await _actor_id(session, owner),
            correlation_id=request.state.correlation_id,
        )
    except (OutreachNotAllowed, OutreachNotFound, ApprovalExpired) as exc:
        raise _raise(exc) from exc
    return _response(row)


@router.post("/drafts/{draft_id}/reject", response_model=OutreachDraftResponse)
async def reject_draft(
    draft_id: UUID,
    payload: OutreachReject,
    request: Request,
    owner: AuthenticatedOwner = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> OutreachDraftResponse:
    try:
        row = await _service(owner, session).reject(
            owner.tenant_id,
            draft_id,
            payload.reason,
            actor_user_id=await _actor_id(session, owner),
            correlation_id=request.state.correlation_id,
        )
    except (OutreachNotAllowed, OutreachNotFound) as exc:
        raise _raise(exc) from exc
    return _response(row)


@router.post("/drafts/{draft_id}/opt-out", response_model=OutreachDraftResponse)
async def opt_out(
    draft_id: UUID,
    request: Request,
    owner: AuthenticatedOwner = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> OutreachDraftResponse:
    try:
        row = await _service(owner, session).opt_out(
            owner.tenant_id, draft_id, correlation_id=request.state.correlation_id
        )
    except OutreachNotFound as exc:
        raise _raise(exc) from exc
    return _response(row)


@router.post("/drafts/{draft_id}/send", response_model=OutreachDraftResponse)
async def send_draft(
    draft_id: UUID,
    payload: OutreachSend,
    request: Request,
    owner: AuthenticatedOwner = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> OutreachDraftResponse:
    try:
        row, duplicate = await _service(owner, session).send(
            owner.tenant_id,
            draft_id,
            payload.idempotency_key,
            correlation_id=request.state.correlation_id,
        )
    except (OutreachNotAllowed, OutreachNotFound, OutreachAlreadySent, ApprovalExpired) as exc:
        raise _raise(exc) from exc
    return _response(row, duplicate)
