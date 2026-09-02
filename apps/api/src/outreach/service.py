from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import AuditEvent, OutboxEvent, OutreachDraft, ProspectResearch
from ..integrations.whatsapp import SessionStatus
from .contracts import OutreachDraftCreate, OutreachEdit
from .gateway import ColdOutreachGateway
from .policy import ConservativeOutreachPolicy, OutreachRateLimited
from ..prospecting.contracts import ProspectResearchResult


class OutreachNotAllowed(RuntimeError):
    pass


class OutreachAlreadySent(RuntimeError):
    pass


class ApprovalExpired(RuntimeError):
    pass


class OutreachNotFound(LookupError):
    pass


class ResearchNotEligible(LookupError):
    pass


class OutreachIdempotencyConflict(ValueError):
    pass


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _normalize_phone(value: str | None) -> str:
    digits = re.sub(r"\D", "", value or "")
    if not 8 <= len(digits) <= 15:
        raise OutreachNotAllowed("BUSINESS_CONTACT_PHONE_REQUIRED")
    return digits


class OutreachService:
    def __init__(
        self,
        session: AsyncSession,
        gateway: ColdOutreachGateway,
        *,
        approval_ttl: timedelta = timedelta(hours=24),
        policy: ConservativeOutreachPolicy | None = None,
    ) -> None:
        self.session = session
        self.gateway = gateway
        self.approval_ttl = approval_ttl
        self.policy = policy or ConservativeOutreachPolicy()

    async def _draft(self, tenant_id: UUID, draft_id: UUID) -> OutreachDraft:
        row = await self.session.scalar(
            select(OutreachDraft).where(
                OutreachDraft.tenant_id == tenant_id,
                OutreachDraft.id == draft_id,
            )
        )
        if row is None:
            raise OutreachNotFound("OUTREACH_DRAFT_NOT_FOUND")
        return row

    async def _research(self, tenant_id: UUID, research_id: UUID) -> ProspectResearch:
        row = await self.session.scalar(
            select(ProspectResearch).where(
                ProspectResearch.tenant_id == tenant_id,
                ProspectResearch.id == research_id,
            )
        )
        if row is None or row.status != "PENDING_REVIEW":
            raise ResearchNotEligible("RESEARCH_NOT_PENDING_REVIEW")
        return row

    async def _recipient_conflict(
        self,
        tenant_id: UUID,
        recipient_ref: str,
        *,
        excluding_draft_id: UUID | None = None,
    ) -> OutreachDraft | None:
        conditions = [
            OutreachDraft.tenant_id == tenant_id,
            OutreachDraft.recipient_ref == recipient_ref,
        ]
        if excluding_draft_id is not None:
            conditions.append(OutreachDraft.id != excluding_draft_id)
        return await self.session.scalar(select(OutreachDraft).where(*conditions))

    def _snapshot(self, research: ProspectResearch) -> tuple[ProspectResearchResult, str, str]:
        result = ProspectResearchResult.model_validate(research.result)
        return result, _hash(research.result), _normalize_phone(result.business_contact.phone)

    async def _audit(
        self,
        tenant_id: UUID,
        action: str,
        target_id: UUID,
        correlation_id: str,
        actor_user_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        self.session.add(
            AuditEvent(
                id=uuid4(),
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                action=action,
                target_type="outreach_draft",
                target_id=target_id,
                correlation_id=correlation_id,
                event_metadata=metadata or {},
                created_at=now,
                updated_at=now,
            )
        )

    async def create(
        self,
        tenant_id: UUID,
        request: OutreachDraftCreate,
        *,
        correlation_id: str,
        actor_user_id: UUID | None = None,
    ) -> tuple[OutreachDraft, bool]:
        research = await self._research(tenant_id, request.research_id)
        result, research_hash, recipient = self._snapshot(research)
        message_hash = _hash(
            {
                "draft_text": request.draft_text,
                "approach_reason": request.approach_reason,
                "recipient": recipient,
            }
        )
        existing = await self.session.scalar(
            select(OutreachDraft).where(
                OutreachDraft.tenant_id == tenant_id,
                OutreachDraft.idempotency_key == request.idempotency_key,
            )
        )
        if existing is not None:
            if existing.research_id != request.research_id or existing.message_hash != message_hash:
                raise OutreachIdempotencyConflict("IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_DATA")
            return existing, True
        existing_research = await self.session.scalar(
            select(OutreachDraft).where(
                OutreachDraft.tenant_id == tenant_id,
                OutreachDraft.research_id == request.research_id,
            )
        )
        if existing_research is not None:
            # One cold-contact draft per researched prospect prevents duplicate
            # first approaches even when different request keys are supplied.
            return existing_research, True
        existing_recipient = await self.session.scalar(
            select(OutreachDraft).where(
                OutreachDraft.tenant_id == tenant_id,
                OutreachDraft.recipient_ref == recipient,
            )
        )
        if existing_recipient is not None:
            # A number may appear in more than one public-source record. Never
            # let a new research row create a second first approach.
            return existing_recipient, True

        now = datetime.now(timezone.utc)
        row = OutreachDraft(
            id=uuid4(),
            tenant_id=tenant_id,
            research_id=research.id,
            idempotency_key=request.idempotency_key,
            company_name=result.company,
            source_url=research.source_url,
            source_data=result.model_dump(mode="json"),
            findings=[finding.model_dump(mode="json") for finding in result.findings[:3]],
            recipient_ref=recipient,
            draft_text=request.draft_text,
            approach_reason=request.approach_reason,
            research_data_hash=research_hash,
            message_hash=message_hash,
            status="PENDING_APPROVAL",
            version=1,
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        await self._audit(
            tenant_id,
            "OUTREACH_DRAFT_CREATED",
            row.id,
            correlation_id,
            actor_user_id,
            {"research_id": str(research.id), "source_host": research.source_url.split("/", 3)[2]},
        )
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            winner = await self.session.scalar(
                select(OutreachDraft).where(
                    OutreachDraft.tenant_id == tenant_id,
                    OutreachDraft.research_id == request.research_id,
                )
            )
            if winner is None:
                raise
            return winner, True
        await self.session.refresh(row)
        return row, False

    async def approve(
        self,
        tenant_id: UUID,
        draft_id: UUID,
        *,
        confirmed: bool,
        actor_user_id: UUID | None,
        correlation_id: str,
    ) -> OutreachDraft:
        if not confirmed:
            raise OutreachNotAllowed("HUMAN_CONFIRMATION_REQUIRED")
        row = await self._draft(tenant_id, draft_id)
        if row.status != "PENDING_APPROVAL":
            raise OutreachNotAllowed("DRAFT_NOT_PENDING_APPROVAL")
        research = await self._research(tenant_id, row.research_id)
        _, research_hash, recipient = self._snapshot(research)
        if research_hash != row.research_data_hash or recipient != row.recipient_ref:
            row.status = "EXPIRED"
            await self.session.commit()
            raise ApprovalExpired("RESEARCH_DATA_CHANGED")
        now = datetime.now(timezone.utc)
        row.status = "APPROVED"
        row.approved_at = now
        row.expires_at = now + self.approval_ttl
        row.approved_by_user_id = actor_user_id
        row.approved_research_data_hash = research_hash
        row.approved_message_hash = row.message_hash
        row.approved_recipient_ref = recipient
        row.version += 1
        row.updated_at = now
        await self._audit(
            tenant_id, "OUTREACH_DRAFT_APPROVED", row.id, correlation_id, actor_user_id
        )
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def edit(
        self,
        tenant_id: UUID,
        draft_id: UUID,
        request: OutreachEdit,
        *,
        actor_user_id: UUID | None,
        correlation_id: str,
    ) -> OutreachDraft:
        row = await self._draft(tenant_id, draft_id)
        if row.status in {"SENDING", "SENT"}:
            raise OutreachNotAllowed("DRAFT_ALREADY_SENT_OR_PROCESSING")
        if request.draft_text is not None:
            row.draft_text = request.draft_text
        if request.approach_reason is not None:
            row.approach_reason = request.approach_reason
        if request.recipient_ref is not None:
            recipient = _normalize_phone(request.recipient_ref)
            if recipient != row.recipient_ref:
                conflict = await self._recipient_conflict(
                    tenant_id,
                    recipient,
                    excluding_draft_id=row.id,
                )
                if conflict is not None:
                    raise OutreachNotAllowed("RECIPIENT_ALREADY_APPROACHED")
            row.recipient_ref = recipient
        row.message_hash = _hash(
            {
                "draft_text": row.draft_text,
                "approach_reason": row.approach_reason,
                "recipient": row.recipient_ref,
            }
        )
        row.status = "PENDING_APPROVAL"
        row.expires_at = None
        row.approved_at = None
        row.approved_by_user_id = None
        row.approved_research_data_hash = None
        row.approved_message_hash = None
        row.approved_recipient_ref = None
        row.version += 1
        row.updated_at = datetime.now(timezone.utc)
        await self._audit(tenant_id, "OUTREACH_DRAFT_EDITED", row.id, correlation_id, actor_user_id)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def reject(
        self,
        tenant_id: UUID,
        draft_id: UUID,
        reason: str,
        *,
        actor_user_id: UUID | None,
        correlation_id: str,
    ) -> OutreachDraft:
        row = await self._draft(tenant_id, draft_id)
        if row.status in {"SENDING", "SENT"}:
            raise OutreachNotAllowed("DRAFT_ALREADY_SENT_OR_PROCESSING")
        now = datetime.now(timezone.utc)
        row.status = "REJECTED"
        row.rejected_at = now
        row.rejection_reason = reason
        row.version += 1
        row.updated_at = now
        await self._audit(
            tenant_id, "OUTREACH_DRAFT_REJECTED", row.id, correlation_id, actor_user_id
        )
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def opt_out(
        self, tenant_id: UUID, draft_id: UUID, *, correlation_id: str
    ) -> OutreachDraft:
        row = await self._draft(tenant_id, draft_id)
        now = datetime.now(timezone.utc)
        row.opted_out_at = now
        if row.status not in {"SENT", "SENDING"}:
            row.status = "PAUSED"
        row.pause_reason = "OPT_OUT"
        row.version += 1
        row.updated_at = now
        await self._audit(tenant_id, "OUTREACH_OPT_OUT", row.id, correlation_id)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def send(
        self,
        tenant_id: UUID,
        draft_id: UUID,
        idempotency_key: str,
        *,
        correlation_id: str,
        now: datetime | None = None,
    ) -> tuple[OutreachDraft, bool]:
        row = await self._draft(tenant_id, draft_id)
        if row.status == "SENT":
            if row.send_idempotency_key == idempotency_key:
                return row, True
            raise OutreachAlreadySent("OUTREACH_ALREADY_SENT")
        if row.opted_out_at is not None:
            raise OutreachNotAllowed("OPT_OUT")
        if row.status != "APPROVED":
            raise OutreachNotAllowed("APPROVAL_REQUIRED")
        current = now or datetime.now(timezone.utc)
        if row.expires_at is None or row.expires_at <= current:
            row.status = "EXPIRED"
            await self.session.commit()
            raise ApprovalExpired("APPROVAL_EXPIRED")
        research = await self._research(tenant_id, row.research_id)
        _, research_hash, recipient = self._snapshot(research)
        if (
            research_hash != row.approved_research_data_hash
            or row.message_hash != row.approved_message_hash
            or recipient != row.approved_recipient_ref
        ):
            row.status = "EXPIRED"
            await self.session.commit()
            raise ApprovalExpired("APPROVAL_SNAPSHOT_CHANGED")
        try:
            await self.policy.allow(tenant_id, current)
            snapshot = await self.gateway.session()
            if (
                snapshot.tenant_id != tenant_id
                or snapshot.status is not SessionStatus.CONNECTED
                or not snapshot.secure
                or not snapshot.owner_ref
            ):
                raise OutreachNotAllowed("SESSION_UNSAFE_OR_DISCONNECTED")
        except OutreachRateLimited as exc:
            row.status = "PAUSED"
            row.pause_reason = str(exc)
            await self.session.commit()
            raise OutreachNotAllowed(str(exc)) from exc
        except OutreachNotAllowed as exc:
            row.status = "PAUSED"
            row.pause_reason = str(exc)
            await self.session.commit()
            raise
        except Exception as exc:
            row.status = "PAUSED"
            row.pause_reason = "SESSION_ERROR"
            await self.session.commit()
            if isinstance(exc, OutreachNotAllowed):
                raise
            raise OutreachNotAllowed("SESSION_ERROR") from exc

        row.status = "SENDING"
        row.send_idempotency_key = idempotency_key
        row.version += 1
        row.updated_at = current
        outbox_key = f"cold-outreach:{row.id}:{idempotency_key}"
        outbox = OutboxEvent(
            id=uuid4(),
            tenant_id=tenant_id,
            aggregate_type="outreach_draft",
            aggregate_id=row.id,
            event_type="COLD_OUTREACH_SEND",
            idempotency_key=outbox_key,
            payload={
                "recipient_ref": recipient,
                "content": row.draft_text,
                "draft_id": str(row.id),
            },
            status="PENDING",
            attempts=0,
            created_at=current,
            updated_at=current,
        )
        self.session.add(outbox)
        await self.session.commit()
        try:
            receipt = await self.gateway.send(
                tenant_id, row.id, recipient, row.draft_text, idempotency_key
            )
        except Exception as exc:
            outbox.status = "FAILED"
            outbox.updated_at = datetime.now(timezone.utc)
            row.status = "PAUSED"
            row.pause_reason = "SEND_FAILED"
            row.updated_at = datetime.now(timezone.utc)
            await self.session.commit()
            raise OutreachNotAllowed("SEND_FAILED") from exc
        row.status = "SENT"
        row.sent_at = current
        row.provider_message_id = receipt.external_message_id
        outbox.status = "DELIVERED"
        outbox.delivered_at = current
        outbox.payload = {
            **outbox.payload,
            "provider_message_id": receipt.external_message_id,
            "delivery_status": receipt.status,
        }
        row.version += 1
        row.updated_at = current
        await self.policy.record(tenant_id, current)
        await self._audit(
            tenant_id, "OUTREACH_SENT", row.id, correlation_id, metadata={"provider": "whatsapp"}
        )
        await self.session.commit()
        await self.session.refresh(row)
        return row, False
