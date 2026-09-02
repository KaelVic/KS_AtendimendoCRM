from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import AuditEvent, ProspectResearch
from .adapter import ProspectResearchAdapter, ProspectResearchError, canonicalize_source_url
from .contracts import ProspectResearchResult, ResearchRequest


class ResearchIdempotencyConflict(ValueError):
    pass


class ProspectResearchService:
    def __init__(
        self,
        session: AsyncSession,
        adapter: ProspectResearchAdapter,
        cache_ttl_seconds: int = 86_400,
    ) -> None:
        self.session = session
        self.adapter = adapter
        self.cache_ttl_seconds = max(0, cache_ttl_seconds)

    async def research(
        self,
        request: ResearchRequest,
        *,
        correlation_id: str,
        actor_user_id: UUID | None = None,
    ) -> tuple[ProspectResearch, bool]:
        source_url = canonicalize_source_url(str(request.source_url))
        source_fingerprint = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
        existing_by_key = await self.session.scalar(
            select(ProspectResearch).where(
                ProspectResearch.tenant_id == request.tenant_id,
                ProspectResearch.idempotency_key == request.idempotency_key,
            )
        )
        if existing_by_key is not None:
            if existing_by_key.source_fingerprint != source_fingerprint:
                raise ResearchIdempotencyConflict("IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_SOURCE")
            return existing_by_key, True

        now = datetime.now(timezone.utc)
        cached = await self.session.scalar(
            select(ProspectResearch).where(
                ProspectResearch.tenant_id == request.tenant_id,
                ProspectResearch.source_fingerprint == source_fingerprint,
            )
        )
        if cached is not None and cached.fetched_at is not None:
            age = now - cached.fetched_at
            if age <= timedelta(seconds=self.cache_ttl_seconds):
                return cached, True

        status = "PENDING_REVIEW"
        failure_code: str | None = None
        try:
            result = await self.adapter.research(request)
            result_json = result.model_dump(mode="json")
            fetched_at = result.fetched_at
        except ProspectResearchError as exc:
            status = "FAILED"
            failure_code = exc.code
            fetched_at = now
            # Empty structured output represents absence of evidence, not a claim.
            result_json = ProspectResearchResult(fetched_at=now).model_dump(mode="json")
        except Exception:
            status = "FAILED"
            failure_code = "RESEARCH_FAILED"
            fetched_at = now
            result_json = ProspectResearchResult(fetched_at=now).model_dump(mode="json")

        if cached is None:
            cached = ProspectResearch(
                id=uuid4(),
                tenant_id=request.tenant_id,
                idempotency_key=request.idempotency_key,
                segment=request.segment,
                source_url=source_url,
                source_fingerprint=source_fingerprint,
                status=status,
                result=result_json,
                fetched_at=fetched_at,
                failure_code=failure_code,
                version=1,
                created_at=now,
                updated_at=now,
            )
            self.session.add(cached)
        else:
            cached.status = status
            cached.result = result_json
            cached.fetched_at = fetched_at
            cached.failure_code = failure_code
            cached.version += 1
            cached.updated_at = now

        self.session.add(
            AuditEvent(
                id=uuid4(),
                tenant_id=request.tenant_id,
                actor_user_id=actor_user_id,
                action="PROSPECT_RESEARCHED",
                target_type="prospect_research",
                target_id=cached.id,
                correlation_id=correlation_id,
                event_metadata={
                    "status": status,
                    "source_host": source_url.split("/", 3)[2],
                    "segment": request.segment,
                    "failure_code": failure_code,
                },
                created_at=now,
                updated_at=now,
            )
        )
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            winner = await self.session.scalar(
                select(ProspectResearch).where(
                    ProspectResearch.tenant_id == request.tenant_id,
                    ProspectResearch.source_fingerprint == source_fingerprint,
                )
            )
            if winner is None:
                raise
            return winner, True
        await self.session.refresh(cached)
        return cached, False
