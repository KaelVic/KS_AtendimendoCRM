from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import AuditEvent, Conversation, Proposal, ProposalItem
from .catalog import CatalogSnapshot, default_catalog
from .contracts import ProposalCreateRequest
from .renderer import TEMPLATE_VERSION, ProposalPdfRenderer, ProposalRenderData
from .storage import ProposalStorage
from .validation import ValidatedProposal, validate_draft


class ProposalIdempotencyConflict(ValueError):
    """The same tenant-scoped key was reused for different input data."""


class ProposalConversationNotFound(LookupError):
    pass


def canonical_hash(data: dict[str, Any]) -> str:
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


class ProposalService:
    """Application service; catalog validation and rendering stay outside the router."""

    def __init__(
        self,
        session: AsyncSession,
        storage: ProposalStorage,
        catalog: CatalogSnapshot | None = None,
        renderer: ProposalPdfRenderer | None = None,
    ) -> None:
        self.session = session
        self.storage = storage
        self.catalog = catalog or default_catalog()
        self.renderer = renderer or ProposalPdfRenderer()

    async def create(
        self,
        request: ProposalCreateRequest,
        *,
        correlation_id: str,
        actor_user_id: UUID | None = None,
        generated_on: date | None = None,
    ) -> tuple[Proposal, bool, ValidatedProposal]:
        conversation = await self.session.scalar(
            select(Conversation).where(
                Conversation.id == request.conversation_id,
                Conversation.tenant_id == request.tenant_id,
            )
        )
        if conversation is None:
            raise ProposalConversationNotFound("CONVERSATION_NOT_FOUND")

        validated = validate_draft(request.draft, self.catalog)
        # Keep the submitted commercial fields in the fingerprint so reusing a
        # key with a different (even invalid) draft cannot masquerade as the
        # original request. Only the validated canonical snapshot feeds PDF.
        data_used = {
            "draft_input": request.draft.model_dump(mode="json"),
            "resolved": validated.canonical_data,
            "template_version": TEMPLATE_VERSION,
        }
        data_hash = canonical_hash(data_used)
        existing = await self.session.scalar(
            select(Proposal).where(
                Proposal.tenant_id == request.tenant_id,
                Proposal.idempotency_key == request.idempotency_key,
            )
        )
        if existing is not None:
            if existing.data_hash != data_hash:
                raise ProposalIdempotencyConflict("IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_DATA")
            return existing, True, validated

        now = datetime.now(timezone.utc)
        pdf_sha256: str | None = None
        pdf_storage_key: str | None = None
        primary = validated.primary_product
        if validated.status == "READY" and primary is not None:
            pdf = self.renderer.render(
                ProposalRenderData(
                    customer=request.draft.customer,
                    need=request.draft.need,
                    product_name=primary.name,
                    scope=primary.scope,
                    total_cents=validated.total_cents,
                    delivery_days=primary.delivery_days,
                    revisions=primary.revisions,
                    observations=tuple(request.draft.observations),
                    catalog_version=validated.catalog_version,
                    generated_on=generated_on or now.date(),
                )
            )
            pdf_sha256 = self.renderer.sha256(pdf)
            pdf_storage_key = self.storage.put(request.tenant_id, data_hash, pdf)

        proposal = Proposal(
            id=uuid4(),
            tenant_id=request.tenant_id,
            conversation_id=request.conversation_id,
            idempotency_key=request.idempotency_key,
            customer_name=request.draft.customer,
            need_summary=request.draft.need,
            product_id=request.draft.product_id,
            catalog_version=validated.catalog_version,
            template_version=TEMPLATE_VERSION,
            status="RENDERED" if validated.renderable else "HUMAN_APPROVAL_REQUIRED",
            approval_reason=(";".join(validated.approval_reasons) or None),
            data_hash=data_hash,
            data_used=data_used,
            pdf_sha256=pdf_sha256,
            pdf_storage_key=pdf_storage_key,
            version=1,
            created_at=now,
            updated_at=now,
        )
        self.session.add(proposal)
        for line in validated.lines:
            self.session.add(
                ProposalItem(
                    id=uuid4(),
                    tenant_id=request.tenant_id,
                    proposal_id=proposal.id,
                    product_id=line["product_id"],
                    product_name=line["product_name"],
                    scope=line["scope"],
                    quantity=line["quantity"],
                    unit_price_cents=line["unit_price_cents"],
                    line_total_cents=line["line_total_cents"],
                    created_at=now,
                    updated_at=now,
                )
            )
        self.session.add(
            AuditEvent(
                id=uuid4(),
                tenant_id=request.tenant_id,
                actor_user_id=actor_user_id,
                action="PROPOSAL_CREATED",
                target_type="proposal",
                target_id=proposal.id,
                correlation_id=correlation_id,
                event_metadata={
                    "status": proposal.status,
                    "data_hash": data_hash,
                    "catalog_version": validated.catalog_version,
                    "template_version": TEMPLATE_VERSION,
                },
                created_at=now,
                updated_at=now,
            )
        )
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = await self.session.scalar(
                select(Proposal).where(
                    Proposal.tenant_id == request.tenant_id,
                    Proposal.idempotency_key == request.idempotency_key,
                )
            )
            if existing is None:
                raise
            if existing.data_hash != data_hash:
                raise ProposalIdempotencyConflict(
                    "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_DATA"
                ) from None
            return existing, True, validated
        await self.session.refresh(proposal)
        return proposal, False, validated
