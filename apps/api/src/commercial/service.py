from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.contracts import PendingItemCreateRequest
from ..db.models import AuditEvent, CommercialOrder, PaymentEvent, Proposal
from ..pending.service import create_pending_item
from .config import PaymentLinkAllowlist
from .contracts import PaymentWebhookPayload


class CommercialFlowError(ValueError):
    pass


class ProposalNotReady(CommercialFlowError):
    pass


class AcceptanceIdempotencyConflict(CommercialFlowError):
    pass


class PaymentEventConflict(CommercialFlowError):
    pass


class PaymentAmountMismatch(CommercialFlowError):
    pass


class PaymentStateRejected(CommercialFlowError):
    pass


@dataclass(frozen=True)
class PaymentResult:
    event: PaymentEvent
    order: CommercialOrder
    duplicate: bool


class PaymentWebhookVerifier:
    """HMAC adapter; the secret is supplied by environment/secret manager only."""

    def __init__(self, secret: str | None):
        self.secret = secret

    def verify(self, body: bytes, signature: str | None) -> bool:
        if not self.secret or not signature:
            return False
        supplied = signature.removeprefix("sha256=")
        expected = hmac.new(self.secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(supplied, expected)


class CommercialFlowService:
    """Deterministic application service for acceptance and trusted payments."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        contract_template_version: str | None = None,
        payment_links: PaymentLinkAllowlist | None = None,
    ) -> None:
        self.session = session
        self.contract_template_version = contract_template_version or None
        self.payment_links = payment_links or PaymentLinkAllowlist(None, ())

    async def accept(
        self,
        tenant_id: UUID,
        proposal_id: UUID,
        idempotency_key: str,
        *,
        correlation_id: str,
        actor_user_id: UUID | None = None,
    ) -> tuple[CommercialOrder, bool]:
        proposal = await self.session.scalar(
            select(Proposal).where(Proposal.tenant_id == tenant_id, Proposal.id == proposal_id)
        )
        if proposal is None:
            raise LookupError("PROPOSAL_NOT_FOUND")
        if proposal.status != "RENDERED":
            raise ProposalNotReady("PROPOSAL_NOT_READY_FOR_ACCEPTANCE")

        existing_by_key = await self.session.scalar(
            select(CommercialOrder).where(
                CommercialOrder.tenant_id == tenant_id,
                CommercialOrder.acceptance_idempotency_key == idempotency_key,
            )
        )
        if existing_by_key is not None:
            if existing_by_key.proposal_id != proposal_id:
                raise AcceptanceIdempotencyConflict("ACCEPTANCE_KEY_REUSED_WITH_DIFFERENT_PROPOSAL")
            return existing_by_key, True

        existing_by_proposal = await self.session.scalar(
            select(CommercialOrder).where(
                CommercialOrder.tenant_id == tenant_id,
                CommercialOrder.proposal_id == proposal_id,
            )
        )
        if existing_by_proposal is not None:
            return existing_by_proposal, True

        resolved = proposal.data_used.get("resolved", proposal.data_used)
        amount_cents = resolved.get("price_cents") if isinstance(resolved, dict) else None
        if not isinstance(amount_cents, int) or amount_cents <= 0:
            raise CommercialFlowError("PROPOSAL_AMOUNT_UNAVAILABLE")

        now = datetime.now(timezone.utc)
        status = "CONTRACT_PENDING"
        contract_ready_at = None
        payment_link_ready_at = None
        payment_link = None
        payment_link_config_version = None
        if self.contract_template_version:
            status = "PAYMENT_LINK_PENDING"
            contract_ready_at = now
            link = self.payment_links.resolve(proposal.product_id, amount_cents)
            if link is not None:
                status = "PAYMENT_PENDING"
                payment_link = link.url
                payment_link_config_version = self.payment_links.version
                payment_link_ready_at = now

        order = CommercialOrder(
            id=uuid4(),
            tenant_id=tenant_id,
            conversation_id=proposal.conversation_id,
            proposal_id=proposal.id,
            acceptance_idempotency_key=idempotency_key,
            status=status,
            expected_amount_cents=amount_cents,
            currency="BRL",
            catalog_version=proposal.catalog_version,
            contract_template_version=self.contract_template_version,
            payment_link_config_version=payment_link_config_version,
            payment_link=payment_link,
            accepted_at=now,
            contract_ready_at=contract_ready_at,
            payment_link_ready_at=payment_link_ready_at,
            version=1,
            created_at=now,
            updated_at=now,
        )
        self.session.add(order)
        self.session.add(
            AuditEvent(
                id=uuid4(),
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                action="COMMERCIAL_ACCEPTANCE_RECORDED",
                target_type="commercial_order",
                target_id=order.id,
                correlation_id=correlation_id,
                event_metadata={"status": status, "amount_cents": amount_cents},
                created_at=now,
                updated_at=now,
            )
        )
        if status == "CONTRACT_PENDING" or status == "PAYMENT_LINK_PENDING":
            pending_kind = "CONTRACT" if status == "CONTRACT_PENDING" else "PAYMENT"
            await create_pending_item(
                self.session,
                PendingItemCreateRequest(
                    tenant_id=tenant_id,
                    conversation_id=proposal.conversation_id,
                    kind=pending_kind,
                    idempotency_key=f"commercial:{order.id}:{pending_kind}",
                ),
                correlation_id,
                actor_user_id,
            )
        else:
            await self.session.commit()
        await self.session.refresh(order)
        return order, False

    async def process_payment(
        self,
        tenant_id: UUID,
        provider: str,
        payload: PaymentWebhookPayload,
        payload_hash: str,
        *,
        correlation_id: str,
    ) -> PaymentResult:
        order = await self.session.scalar(
            select(CommercialOrder).where(
                CommercialOrder.id == payload.payment_reference,
                CommercialOrder.tenant_id == tenant_id,
            )
        )
        if order is None:
            raise LookupError("COMMERCIAL_ORDER_NOT_FOUND")

        event = await self.session.scalar(
            select(PaymentEvent).where(
                PaymentEvent.tenant_id == tenant_id,
                PaymentEvent.provider == provider,
                PaymentEvent.external_event_id == payload.external_event_id,
            )
        )
        if event is not None and event.payload_hash != payload_hash:
            raise PaymentEventConflict("PAYMENT_EVENT_REUSED_WITH_DIFFERENT_PAYLOAD")
        if event is None:
            now = datetime.now(timezone.utc)
            event = PaymentEvent(
                id=uuid4(),
                tenant_id=tenant_id,
                commercial_order_id=order.id,
                provider=provider,
                external_event_id=payload.external_event_id,
                event_type=payload.event_type,
                payload_hash=payload_hash,
                amount_cents=payload.amount_cents,
                currency=payload.currency,
                outcome="RECEIVED",
                created_at=now,
                updated_at=now,
            )
            self.session.add(event)
            try:
                await self.session.commit()
            except IntegrityError:
                await self.session.rollback()
                event = await self.session.scalar(
                    select(PaymentEvent).where(
                        PaymentEvent.tenant_id == tenant_id,
                        PaymentEvent.provider == provider,
                        PaymentEvent.external_event_id == payload.external_event_id,
                    )
                )
                if event is None:
                    raise
                if event.payload_hash != payload_hash:
                    raise PaymentEventConflict("PAYMENT_EVENT_REUSED_WITH_DIFFERENT_PAYLOAD")
        elif event.outcome != "RECEIVED":
            return PaymentResult(event, order, True)

        # The order lock serializes two distinct payment events for one order.
        order = await self.session.scalar(
            select(CommercialOrder)
            .where(CommercialOrder.id == order.id, CommercialOrder.tenant_id == tenant_id)
            .with_for_update()
        )
        now = datetime.now(timezone.utc)
        if (
            payload.currency != order.currency
            or payload.amount_cents != order.expected_amount_cents
        ):
            event.outcome = "REJECTED_AMOUNT"
            event.processed_at = now
            event.updated_at = now
            await self.session.commit()
            raise PaymentAmountMismatch("PAYMENT_AMOUNT_OR_CURRENCY_MISMATCH")
        if payload.event_type != "PAYMENT_CONFIRMED":
            event.outcome = "REJECTED_TYPE"
            event.processed_at = now
            event.updated_at = now
            await self.session.commit()
            return PaymentResult(event, order, False)
        if order.status in {"CANCELLED", "REFUNDED"}:
            event.outcome = "REJECTED_STATE"
            event.processed_at = now
            event.updated_at = now
            await self.session.commit()
            raise PaymentStateRejected("PAYMENT_NOT_ALLOWED_FOR_ORDER_STATE")
        if order.status == "ONBOARDING_READY":
            event.outcome = "DUPLICATE"
            event.processed_at = now
            event.updated_at = now
            await self.session.commit()
            return PaymentResult(event, order, True)
        if order.status != "PAYMENT_PENDING":
            event.outcome = "REJECTED_STATE"
            event.processed_at = now
            event.updated_at = now
            await self.session.commit()
            raise PaymentStateRejected("PAYMENT_LINK_NOT_READY")

        order.status = "ONBOARDING_READY"
        order.paid_at = now
        order.onboarding_released_at = now
        order.version += 1
        order.updated_at = now
        event.outcome = "PROCESSED"
        event.processed_at = now
        event.updated_at = now
        self.session.add(
            AuditEvent(
                id=uuid4(),
                tenant_id=tenant_id,
                action="PAYMENT_CONFIRMED_ONBOARDING_RELEASED",
                target_type="commercial_order",
                target_id=order.id,
                correlation_id=correlation_id,
                event_metadata={"amount_cents": payload.amount_cents, "provider": provider},
                created_at=now,
                updated_at=now,
            )
        )
        await self.session.commit()
        return PaymentResult(event, order, False)
