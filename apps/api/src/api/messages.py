from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .contracts import (
    ConversationSummary,
    ControlActionRequest,
    ControlResponse,
    AssistedResponseRequest,
    AssistedResponseResponse,
    MessageResponse,
    PaginatedConversations,
    PaginatedMessages,
    SendMessageRequest,
    SimulatedMessageRequest,
    SimulatedMessageResponse,
    PendingItemCreateRequest,
)
from .dependencies import get_db_session, require_owner, require_tenant
from ..control import (
    ControlAction,
    AssistedDraft,
    ControlService,
    ControlStateError,
    ControlBusy,
    RedisControlEventPublisher,
    RedisConversationGate,
    StaleControlVersion,
)
from ..db.models import AuditEvent, Conversation, ConversationControl, Message, User
from ..redis.client import redis_client
from ..services.auth import AuthenticatedOwner
from ..services.messages import create_simulated_message
from ..pending.service import create_pending_item

router = APIRouter(prefix="/simulator", tags=["Message Simulator"])


inbox_router = APIRouter(prefix="/inbox", tags=["Inbox"])


@inbox_router.get("/conversations", response_model=PaginatedConversations)
async def list_conversations(
    tenant_id: UUID = Query(...),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    owner: AuthenticatedOwner = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
):
    require_tenant(owner, tenant_id)
    rows = list(
        await session.execute(
            select(Conversation, ConversationControl.state, ConversationControl.version)
            .join(
                ConversationControl,
                (ConversationControl.conversation_id == Conversation.id)
                & (ConversationControl.tenant_id == Conversation.tenant_id),
            )
            .where(Conversation.tenant_id == tenant_id)
            .order_by(Conversation.updated_at.desc(), Conversation.id)
            .offset(offset)
            .limit(limit + 1)
        )
    )
    return PaginatedConversations(
        items=[
            ConversationSummary(
                id=conversation.id,
                tenant_id=conversation.tenant_id,
                contact_id=conversation.contact_id,
                channel=conversation.channel,
                status=conversation.status,
                control_state=state,
                control_version=version,
                updated_at=conversation.updated_at,
            )
            for conversation, state, version in rows[:limit]
        ],
        limit=limit,
        offset=offset,
        has_more=len(rows) > limit,
    )


@inbox_router.post("/conversations/{conversation_id}/messages", response_model=MessageResponse, status_code=201)
async def send_message(
    conversation_id: UUID,
    payload: SendMessageRequest,
    request: Request,
    tenant_id: UUID = Query(...),
    owner: AuthenticatedOwner = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
):
    require_tenant(owner, tenant_id)
    conversation = await session.scalar(
        select(Conversation).where(Conversation.id == conversation_id, Conversation.tenant_id == tenant_id)
    )
    if not conversation:
        raise HTTPException(status_code=404, detail={"error_code": "CONVERSATION_NOT_FOUND", "message": "Conversa não encontrada"})
    control = await session.scalar(
        select(ConversationControl).where(
            ConversationControl.conversation_id == conversation_id,
            ConversationControl.tenant_id == tenant_id,
        )
    )
    if not control or control.state != "HUMAN_ACTIVE":
        raise HTTPException(status_code=409, detail={"error_code": "HUMAN_CONTROL_REQUIRED", "message": "Assuma a conversa antes de enviar"})
    existing = await session.scalar(
        select(Message).where(Message.tenant_id == tenant_id, Message.idempotency_key == payload.idempotency_key)
    )
    if existing:
        return existing
    from datetime import datetime, timezone
    from uuid import uuid4
    now = datetime.now(timezone.utc)
    message = Message(
        id=uuid4(), tenant_id=tenant_id, conversation_id=conversation_id, channel=conversation.channel,
        idempotency_key=payload.idempotency_key, direction="OUTBOUND", message_type=payload.message_type,
        content=payload.content, created_at=now, updated_at=now,
    )
    session.add(message)
    conversation.updated_at = now
    session.add(AuditEvent(
        id=uuid4(), tenant_id=tenant_id, action="MESSAGE_SENT_BY_OWNER", target_type="message",
        target_id=message.id, correlation_id=request.state.correlation_id, event_metadata={"channel": conversation.channel},
        created_at=now, updated_at=now,
    ))
    await session.commit()
    await session.refresh(message)
    return message


@inbox_router.post("/conversations/{conversation_id}/control", response_model=ControlResponse)
async def change_control(
    conversation_id: UUID,
    payload: ControlActionRequest,
    request: Request,
    tenant_id: UUID = Query(...),
    owner: AuthenticatedOwner = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
):
    require_tenant(owner, tenant_id)
    actor_user_id = await session.scalar(
        select(User.id).where(User.tenant_id == tenant_id, User.email == owner.email)
    )
    service = ControlService(
        session,
        RedisControlEventPublisher(redis_client),
        RedisConversationGate(redis_client),
    )
    try:
        if payload.action == "RETURN":
            event = await service.return_to_bot(
                tenant_id=tenant_id, conversation_id=conversation_id,
                expected_version=payload.expected_version, actor_user_id=actor_user_id,
                reason=payload.reason, correlation_id=request.state.correlation_id,
            )
        else:
            event = await service.transition(
                tenant_id=tenant_id, conversation_id=conversation_id,
                action=ControlAction(payload.action), expected_version=payload.expected_version,
                actor_user_id=actor_user_id, reason=payload.reason,
                correlation_id=request.state.correlation_id,
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"error_code": str(exc), "message": "Conversa não encontrada"}) from exc
    except StaleControlVersion as exc:
        raise HTTPException(status_code=409, detail={"error_code": "CONTROL_VERSION_CONFLICT", "message": str(exc)}) from exc
    except ControlBusy as exc:
        raise HTTPException(status_code=409, detail={"error_code": "CONTROL_BUSY", "message": str(exc)}) from exc
    except ControlStateError as exc:
        raise HTTPException(status_code=409, detail={"error_code": "INVALID_CONTROL_TRANSITION", "message": str(exc)}) from exc
    if payload.action == "REQUEST_ASSIST":
        # The control transition is already persisted; this idempotent domain
        # record makes the required owner action visible to the CRM.
        await create_pending_item(
            session,
            PendingItemCreateRequest(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                kind="HUMAN_REQUESTED",
                idempotency_key=f"control-assist:{conversation_id}:{event.version}",
            ),
            request.state.correlation_id,
            actor_user_id,
        )
    return ControlResponse(
        conversation_id=conversation_id, tenant_id=tenant_id, state=event.state.value,
        version=event.version, previous_state=event.previous_state.value, event_id=event.event_id,
    )


@inbox_router.post(
    "/conversations/{conversation_id}/assisted-response",
    response_model=AssistedResponseResponse,
)
async def resolve_assisted_response(
    conversation_id: UUID,
    payload: AssistedResponseRequest,
    request: Request,
    tenant_id: UUID = Query(...),
    owner: AuthenticatedOwner = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
):
    require_tenant(owner, tenant_id)
    actor_user_id = await session.scalar(
        select(User.id).where(User.tenant_id == tenant_id, User.email == owner.email)
    )
    service = ControlService(
        session, RedisControlEventPublisher(redis_client), RedisConversationGate(redis_client)
    )
    approved_draft = (
        AssistedDraft(
            content=payload.approved_draft.content,
            facts_hash=payload.approved_draft.facts_hash,
            policy_version=payload.approved_draft.policy_version,
        )
        if payload.approved_draft
        else None
    )
    try:
        draft = await service.resolve_assisted(
            tenant_id=tenant_id, conversation_id=conversation_id,
            expected_version=payload.expected_version, actor_user_id=actor_user_id,
            human_content=payload.human_content, approved_draft=approved_draft,
            tone=payload.tone, correlation_id=request.state.correlation_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"error_code": str(exc), "message": "Conversa não encontrada"}) from exc
    except StaleControlVersion as exc:
        raise HTTPException(status_code=409, detail={"error_code": "CONTROL_VERSION_CONFLICT", "message": str(exc)}) from exc
    except ControlStateError as exc:
        raise HTTPException(status_code=409, detail={"error_code": "ASSISTED_RESPONSE_REJECTED", "message": str(exc)}) from exc
    return AssistedResponseResponse(
        content=draft.content, facts_hash=draft.facts_hash, state="HUMAN_ACTIVE",
        version=payload.expected_version + 1,
    )


@router.post("/messages", response_model=SimulatedMessageResponse, status_code=status.HTTP_201_CREATED)
async def simulate_message(
    payload: SimulatedMessageRequest,
    request: Request,
    owner: AuthenticatedOwner = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
):
    require_tenant(owner, payload.tenant_id)
    try:
        message, contact, conversation, duplicate = await create_simulated_message(
            session, payload, request.state.correlation_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"error_code": str(exc), "message": "Recurso nÃ£o encontrado"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"error_code": "DATA_INTEGRITY_ERROR", "message": str(exc)}) from exc
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail={"error_code": "IDEMPOTENCY_CONFLICT", "message": "RequisiÃ§Ã£o duplicada ou conflitante"},
        ) from exc
    return SimulatedMessageResponse(
        message_id=message.id,
        tenant_id=message.tenant_id,
        conversation_id=conversation.id,
        contact_id=contact.id,
        idempotency_key=message.idempotency_key,
        duplicate=duplicate,
        created_at=message.created_at,
    )


@router.get("/conversations/{conversation_id}/messages", response_model=PaginatedMessages)
async def list_messages(
    conversation_id: UUID,
    tenant_id: UUID = Query(...),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    owner: AuthenticatedOwner = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
):
    require_tenant(owner, tenant_id)
    conversation_exists = await session.scalar(
        select(Conversation.id).where(Conversation.id == conversation_id, Conversation.tenant_id == tenant_id)
    )
    if not conversation_exists:
        raise HTTPException(status_code=404, detail={"error_code": "CONVERSATION_NOT_FOUND", "message": "Conversa nÃ£o encontrada"})
    rows = list(
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.tenant_id == tenant_id)
            .order_by(Message.created_at, Message.id)
            .offset(offset)
            .limit(limit + 1)
        )
    )
    return PaginatedMessages(
        items=[MessageResponse.model_validate(row) for row in rows[:limit]],
        limit=limit,
        offset=offset,
        has_more=len(rows) > limit,
    )
