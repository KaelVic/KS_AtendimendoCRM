import pytest

from src.contacts.optout import is_opt_out_message
from src.integrations.whatsapp import (
    FakeWhatsAppGateway,
    OutboundMessage,
    OutboxDispatcher,
    SessionSnapshot,
    SessionStatus,
    UnsafeSessionError,
)


def test_opt_out_recognizes_explicit_requests_only():
    assert is_opt_out_message("Pare!")
    assert is_opt_out_message("não quero receber mais")
    assert is_opt_out_message("remova meu contato")
    assert not is_opt_out_message("quero cancelar a reunião")


class Store:
    async def mark_delivered(self, idempotency_key, receipt):
        self.receipt = receipt

    async def is_recipient_opted_out(self, tenant_id, contact_id):
        return True


@pytest.mark.asyncio
async def test_automatic_dispatch_is_blocked_for_opted_out_contact():
    from uuid import UUID, uuid4

    tenant = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    gateway = FakeWhatsAppGateway(
        SessionSnapshot(
            tenant_id=tenant,
            session_id="optout-session",
            owner_ref="owner",
            status=SessionStatus.CONNECTED,
            secure=True,
        )
    )
    message = OutboundMessage(
        tenant_id=tenant,
        conversation_id=uuid4(),
        session_id="optout-session",
        recipient_ref="synthetic-recipient",
        recipient_contact_id=uuid4(),
        content="synthetic",
        idempotency_key="optout-idempotency",
    )

    with pytest.raises(UnsafeSessionError, match="opt-out"):
        await OutboxDispatcher(gateway, Store()).dispatch(message)

    assert gateway.sent == {}
