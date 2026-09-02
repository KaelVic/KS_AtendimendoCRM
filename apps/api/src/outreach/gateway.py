from __future__ import annotations

from typing import Protocol
from uuid import UUID

from ..integrations.whatsapp import (
    GatewayReceipt,
    OutboundMessage,
    SessionSnapshot,
    WhatsAppAdapter,
)


class ColdOutreachGateway(Protocol):
    async def session(self) -> SessionSnapshot: ...

    async def send(
        self,
        tenant_id: UUID,
        draft_id: UUID,
        recipient_ref: str,
        content: str,
        idempotency_key: str,
    ) -> GatewayReceipt: ...


class WhatsAppColdOutreachGateway:
    """Transport adapter; all approval and policy rules stay in OutreachService."""

    def __init__(self, adapter: WhatsAppAdapter):
        self.adapter = adapter

    async def session(self) -> SessionSnapshot:
        return await self.adapter.session()

    async def send(
        self,
        tenant_id: UUID,
        draft_id: UUID,
        recipient_ref: str,
        content: str,
        idempotency_key: str,
    ) -> GatewayReceipt:
        return await self.adapter.send(
            OutboundMessage(
                tenant_id=tenant_id,
                conversation_id=draft_id,
                session_id=(await self.adapter.session()).session_id,
                recipient_ref=recipient_ref,
                content=content,
                idempotency_key=idempotency_key,
                automated=True,
            )
        )


class OutreachGatewayError(RuntimeError):
    pass


class FakeColdOutreachGateway:
    """Deterministic transport fake; it never contacts a real number."""

    def __init__(self, snapshot: SessionSnapshot):
        self._snapshot = snapshot
        self.sent: dict[str, GatewayReceipt] = {}

    async def session(self) -> SessionSnapshot:
        return self._snapshot

    async def send(
        self,
        tenant_id: UUID,
        draft_id: UUID,
        recipient_ref: str,
        content: str,
        idempotency_key: str,
    ) -> GatewayReceipt:
        if idempotency_key in self.sent:
            return self.sent[idempotency_key]
        receipt = GatewayReceipt(external_message_id=f"fake-{draft_id}", status="SENT")
        self.sent[idempotency_key] = receipt
        return receipt
