from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import AuditEvent, Contact, Conversation, ConversationControl, Message
from ..api.contracts import SimulatedMessageRequest


async def create_simulated_message(
    session: AsyncSession,
    request: SimulatedMessageRequest,
    correlation_id: str,
) -> tuple[Message, Contact, Conversation, bool]:
    existing = await session.scalar(
        select(Message).where(
            Message.tenant_id == request.tenant_id,
            Message.idempotency_key == request.idempotency_key,
        )
    )
    if existing:
        conversation = await session.scalar(
            select(Conversation).where(
                Conversation.id == existing.conversation_id,  # type: ignore[arg-type]
                Conversation.tenant_id == request.tenant_id,
            )
        )
        contact = await session.scalar(
            select(Contact).where(
                Contact.id == conversation.contact_id,  # type: ignore[arg-type,union-attr]
                Contact.tenant_id == request.tenant_id,
            )
        )
        if not conversation or not contact:
            raise ValueError("Mensagem idempotente aponta para dados inconsistentes")
        return existing, contact, conversation, True

    now = datetime.now(timezone.utc)
    contact = None
    if request.contact_id:
        contact = await session.scalar(
            select(Contact).where(Contact.id == request.contact_id, Contact.tenant_id == request.tenant_id)
        )
        if not contact:
            raise LookupError("CONTACT_NOT_FOUND")
    if not contact:
        contact = Contact(
            id=uuid4(),
            tenant_id=request.tenant_id,
            normalized_phone=request.sender_phone,
            created_at=now,
            updated_at=now,
        )
        session.add(contact)

    conversation = None
    if request.conversation_id:
        conversation = await session.scalar(
            select(Conversation).where(
                Conversation.id == request.conversation_id,
                Conversation.tenant_id == request.tenant_id,
            )
        )
        if not conversation:
            raise LookupError("CONVERSATION_NOT_FOUND")
    if not conversation:
        conversation = Conversation(
            id=uuid4(),
            tenant_id=request.tenant_id,
            contact_id=contact.id,
            channel=request.channel,
            created_at=now,
            updated_at=now,
        )
        session.add(conversation)
        session.add(
            ConversationControl(
                id=uuid4(),
                tenant_id=request.tenant_id,
                conversation_id=conversation.id,
                created_at=now,
                updated_at=now,
            )
        )

    message = Message(
        id=uuid4(),
        tenant_id=request.tenant_id,
        conversation_id=conversation.id,
        channel=request.channel,
        external_message_id=request.external_message_id,
        idempotency_key=request.idempotency_key,
        direction="INBOUND",
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
            tenant_id=request.tenant_id,
            action="MESSAGE_SIMULATED",
            target_type="message",
            target_id=message.id,
            correlation_id=correlation_id,
            event_metadata={"channel": request.channel, "idempotency_key": request.idempotency_key},
            created_at=now,
            updated_at=now,
        )
    )
    await session.commit()
    await session.refresh(message)
    return message, contact, conversation, False
