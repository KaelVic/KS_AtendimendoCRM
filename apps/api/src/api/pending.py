from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .contracts import (
    PaginatedPendingItems,
    PendingItemCreateRequest,
    PendingItemResponse,
    PendingNotificationSummary,
    PendingResolutionRequest,
    SendMessageRequest,
    MessageResponse,
)
from .dependencies import get_db_session, require_owner, require_tenant
from ..db.models import PendingItem, PendingNotification, User
from ..pending.service import create_pending_item, resolve_pending_item, respond_to_pending_item
from ..services.auth import AuthenticatedOwner


router = APIRouter(prefix="/inbox", tags=["Pending items"])


async def _response(session: AsyncSession, item: PendingItem) -> PendingItemResponse:
    notification = await session.scalar(
        select(PendingNotification)
        .where(
            PendingNotification.tenant_id == item.tenant_id,
            PendingNotification.pending_item_id == item.id,
        )
        .order_by(PendingNotification.window_index.desc())
    )
    return PendingItemResponse(
        id=item.id,
        tenant_id=item.tenant_id,
        conversation_id=item.conversation_id,
        kind=item.kind,
        status=item.status,
        due_at=item.due_at,
        created_at=item.created_at,
        resolved_at=item.resolved_at,
        last_notification=(
            PendingNotificationSummary(
                status=notification.status,
                window_index=notification.window_index,
                attempts=notification.attempts,
                sent_at=notification.sent_at,
                next_attempt_at=notification.next_attempt_at,
            )
            if notification
            else None
        ),
    )


@router.get("/pending-items", response_model=PaginatedPendingItems)
async def list_pending_items(
    tenant_id: UUID = Query(...),
    status_filter: str | None = Query(default=None, alias="status", pattern="^(OPEN|RESOLVED)$"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    owner: AuthenticatedOwner = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
):
    require_tenant(owner, tenant_id)
    query = select(PendingItem).where(PendingItem.tenant_id == tenant_id)
    if status_filter:
        query = query.where(PendingItem.status == status_filter)
    rows = list(
        await session.scalars(
            query.order_by(PendingItem.status, PendingItem.due_at, PendingItem.created_at)
            .offset(offset)
            .limit(limit + 1)
        )
    )
    return PaginatedPendingItems(
        items=[await _response(session, item) for item in rows[:limit]],
        limit=limit,
        offset=offset,
        has_more=len(rows) > limit,
    )


@router.post("/pending-items", response_model=PendingItemResponse, status_code=status.HTTP_201_CREATED)
async def create_pending(
    payload: PendingItemCreateRequest,
    request: Request,
    owner: AuthenticatedOwner = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
):
    require_tenant(owner, payload.tenant_id)
    actor = await session.scalar(select(User.id).where(User.tenant_id == owner.tenant_id, User.email == owner.email))
    try:
        item, duplicate = await create_pending_item(session, payload, request.state.correlation_id, actor)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"error_code": str(exc), "message": "Conversa não encontrada"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"error_code": str(exc), "message": "Chave idempotente conflitante"}) from exc
    response = await _response(session, item)
    if duplicate:
        return response
    return response


@router.post("/pending-items/{pending_item_id}/resolve", response_model=PendingItemResponse)
async def resolve_pending(
    pending_item_id: UUID,
    payload: PendingResolutionRequest,
    request: Request,
    tenant_id: UUID = Query(...),
    owner: AuthenticatedOwner = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
):
    require_tenant(owner, tenant_id)
    actor = await session.scalar(select(User.id).where(User.tenant_id == tenant_id, User.email == owner.email))
    try:
        item = await resolve_pending_item(
            session,
            tenant_id=tenant_id,
            pending_item_id=pending_item_id,
            actor_user_id=actor,
            reason=payload.reason,
            correlation_id=request.state.correlation_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"error_code": str(exc), "message": "Pendência não encontrada"}) from exc
    return await _response(session, item)


@router.post("/pending-items/{pending_item_id}/respond", response_model=MessageResponse)
async def respond_pending(
    pending_item_id: UUID,
    payload: SendMessageRequest,
    request: Request,
    tenant_id: UUID = Query(...),
    owner: AuthenticatedOwner = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
):
    require_tenant(owner, tenant_id)
    actor = await session.scalar(select(User.id).where(User.tenant_id == tenant_id, User.email == owner.email))
    try:
        message, _, _ = await respond_to_pending_item(
            session,
            tenant_id=tenant_id,
            pending_item_id=pending_item_id,
            request=payload,
            actor_user_id=actor,
            correlation_id=request.state.correlation_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"error_code": str(exc), "message": "Pendência não encontrada"}) from exc
    except RuntimeError as exc:
        code = str(exc)
        raise HTTPException(
            status_code=409,
            detail={"error_code": code, "message": "A pendência não pode ser respondida neste estado"},
        ) from exc
    return message
