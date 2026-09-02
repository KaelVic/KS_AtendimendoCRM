from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.contracts import PendingItemCreateRequest, SendMessageRequest
from ..db.models import (
    AuditEvent,
    Conversation,
    ConversationControl,
    Message,
    PendingItem,
    PendingNotification,
)


async def create_pending_item(
    session: AsyncSession,
    request: PendingItemCreateRequest,
    correlation_id: str,
    actor_user_id: UUID | None = None,
) -> tuple[PendingItem, bool]:
    existing = await session.scalar(
        select(PendingItem).where(
            PendingItem.tenant_id == request.tenant_id,
            PendingItem.idempotency_key == request.idempotency_key,
        )
    )
    if existing:
        if existing.conversation_id != request.conversation_id:
            raise ValueError("IDEMPOTENCY_CONFLICT")
        return existing, True

    conversation = await session.scalar(
        select(Conversation).where(
            Conversation.id == request.conversation_id,
            Conversation.tenant_id == request.tenant_id,
        )
    )
    if conversation is None:
        raise LookupError("CONVERSATION_NOT_FOUND")

    now = datetime.now(timezone.utc)
    due_at = request.due_at or now
    item = PendingItem(
        id=uuid4(),
        tenant_id=request.tenant_id,
        conversation_id=request.conversation_id,
        kind=request.kind,
        idempotency_key=request.idempotency_key,
        status="OPEN",
        due_at=due_at,
        version=1,
        created_at=now,
        updated_at=now,
    )
    notification = PendingNotification(
        id=uuid4(),
        tenant_id=request.tenant_id,
        pending_item_id=item.id,
        window_index=0,
        idempotency_key=f"pending:{item.id}:window:0",
        correlation_id=correlation_id,
        status="PENDING",
        attempts=0,
        next_attempt_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add_all([item, notification])
    session.add(
        AuditEvent(
            id=uuid4(),
            tenant_id=request.tenant_id,
            actor_user_id=actor_user_id,
            action="PENDING_ITEM_CREATED",
            target_type="pending_item",
            target_id=item.id,
            correlation_id=correlation_id,
            event_metadata={"kind": request.kind},
            created_at=now,
            updated_at=now,
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        # A concurrent creator may have won the tenant-scoped idempotency key.
        await session.rollback()
        existing = await session.scalar(
            select(PendingItem).where(
                PendingItem.tenant_id == request.tenant_id,
                PendingItem.idempotency_key == request.idempotency_key,
            )
        )
        if existing is None:
            raise
        return existing, True
    await session.refresh(item)
    return item, False


async def resolve_pending_item(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    pending_item_id: UUID,
    actor_user_id: UUID | None,
    reason: str,
    correlation_id: str,
) -> PendingItem:
    item = await session.scalar(
        select(PendingItem).where(
            PendingItem.id == pending_item_id,
            PendingItem.tenant_id == tenant_id,
        )
    )
    if item is None:
        raise LookupError("PENDING_ITEM_NOT_FOUND")
    if item.status == "RESOLVED":
        return item

    now = datetime.now(timezone.utc)
    changed = await session.execute(
        update(PendingItem)
        .where(
            PendingItem.id == pending_item_id,
            PendingItem.tenant_id == tenant_id,
            PendingItem.status == "OPEN",
            PendingItem.version == item.version,
        )
        .values(
            status="RESOLVED",
            version=PendingItem.version + 1,
            resolved_at=now,
            resolved_by_user_id=actor_user_id,
            resolution_reason=reason[:500],
            updated_at=now,
        )
    )
    if getattr(changed, "rowcount", 0) != 1:
        await session.rollback()
        raise RuntimeError("PENDING_ITEM_CONCURRENT_UPDATE")
    await session.execute(
        update(PendingNotification)
        .where(
            PendingNotification.tenant_id == tenant_id,
            PendingNotification.pending_item_id == pending_item_id,
            PendingNotification.status.in_(["PENDING", "FAILED"]),
        )
        .values(status="CANCELLED", updated_at=now)
    )
    session.add(
        AuditEvent(
            id=uuid4(),
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="PENDING_ITEM_RESOLVED",
            target_type="pending_item",
            target_id=pending_item_id,
            correlation_id=correlation_id,
            event_metadata={"reason": reason[:500]},
            created_at=now,
            updated_at=now,
        )
    )
    await session.commit()
    await session.refresh(item)
    return item


async def respond_to_pending_item(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    pending_item_id: UUID,
    request: SendMessageRequest,
    actor_user_id: UUID | None,
    correlation_id: str,
) -> tuple[Message, PendingItem, bool]:
    item = await session.scalar(
        select(PendingItem).where(
            PendingItem.id == pending_item_id,
            PendingItem.tenant_id == tenant_id,
        )
    )
    if item is None:
        raise LookupError("PENDING_ITEM_NOT_FOUND")
    conversation = await session.scalar(
        select(Conversation).where(
            Conversation.id == item.conversation_id,
            Conversation.tenant_id == tenant_id,
        )
    )
    control = await session.scalar(
        select(ConversationControl).where(
            ConversationControl.tenant_id == tenant_id,
            ConversationControl.conversation_id == item.conversation_id,
        )
    )
    if conversation is None:
        raise LookupError("CONVERSATION_NOT_FOUND")
    existing = await session.scalar(
        select(Message).where(
            Message.tenant_id == tenant_id,
            Message.idempotency_key == request.idempotency_key,
        )
    )
    if existing:
        if existing.conversation_id != item.conversation_id:
            raise RuntimeError("IDEMPOTENCY_CONFLICT")
        return existing, item, True
    if item.status != "OPEN":
        raise RuntimeError("PENDING_ITEM_ALREADY_RESOLVED")
    if control is None or control.state != "HUMAN_ACTIVE":
        raise RuntimeError("HUMAN_CONTROL_REQUIRED")

    now = datetime.now(timezone.utc)
    message = Message(
        id=uuid4(),
        tenant_id=tenant_id,
        conversation_id=item.conversation_id,
        channel=conversation.channel,
        idempotency_key=request.idempotency_key,
        direction="OUTBOUND",
        message_type=request.message_type,
        content=request.content,
        created_at=now,
        updated_at=now,
    )
    session.add(message)
    conversation.updated_at = now
    session.add(
        AuditEvent(
            id=uuid4(),
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="PENDING_ITEM_RESPONDED",
            target_type="pending_item",
            target_id=pending_item_id,
            correlation_id=correlation_id,
            event_metadata={"message_id": str(message.id)},
            created_at=now,
            updated_at=now,
        )
    )
    await session.flush()
    await resolve_pending_item(
        session,
        tenant_id=tenant_id,
        pending_item_id=pending_item_id,
        actor_user_id=actor_user_id,
        reason="resposta efetiva enviada pelo proprietário",
        correlation_id=correlation_id,
    )
    await session.refresh(message)
    return message, item, False
