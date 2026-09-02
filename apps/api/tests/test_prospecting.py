from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import HttpUrl

from src.db.models import Base, ProspectResearch
from src.prospecting.contracts import (
    BusinessContact,
    DigitalPresence,
    ProspectResearchResult,
    ResearchRequest,
    VerifiableFinding,
)
from src.prospecting.fake import FakeProspectResearchAdapter
from src.prospecting.service import ProspectResearchService, ResearchIdempotencyConflict


class FakeSession:
    def __init__(self) -> None:
        self.rows: list[ProspectResearch] = []
        self.added: list[object] = []
        self.commits = 0

    async def scalar(self, statement):
        params = statement.compile().params
        tenant_id = next((value for key, value in params.items() if key.startswith("tenant_id")), None)
        if "idempotency_key_1" in params:
            for row in self.rows:
                key = next((value for name, value in params.items() if name.startswith("idempotency_key")), None)
                if row.tenant_id == tenant_id and row.idempotency_key == key:
                    return row
        if "source_fingerprint_1" in params:
            fingerprint = next((value for key, value in params.items() if key.startswith("source_fingerprint")), None)
            return next(
                (
                    row
                    for row in self.rows
                    if row.tenant_id == tenant_id and row.source_fingerprint == fingerprint
                ),
                None,
            )
        return None

    def add(self, value: object) -> None:
        self.added.append(value)
        if isinstance(value, ProspectResearch):
            self.rows.append(value)

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, value: object) -> None:
        return None

    async def rollback(self) -> None:
        return None


def result() -> ProspectResearchResult:
    source = HttpUrl("https://clinic.example/area")
    return ProspectResearchResult(
        company="Clínica Exemplo",
        business_contact=BusinessContact(email="contato@clinic.example", source_url=source),
        evidence_urls=[source],
        fetched_at=datetime.now(timezone.utc),
        digital_presence=DigitalPresence(website=True),
        findings=[VerifiableFinding(claim="O site publica contato empresarial.", evidence_url=source)],
    )


def request(key: str = "research-1", tenant_id=None) -> ResearchRequest:
    return ResearchRequest(
        tenant_id=tenant_id or uuid4(),
        idempotency_key=key,
        source_url="https://clinic.example/area",
    )


def test_research_schema_is_tenant_scoped_and_idempotent():
    table = Base.metadata.tables["prospect_researches"]
    constraints = {constraint.name for constraint in table.constraints}

    assert "tenant_id" in table.c
    assert "uq_prospect_research_source" in constraints
    assert "uq_prospect_research_idempotency" in constraints
    assert "ck_prospect_research_status" in constraints


@pytest.mark.asyncio
async def test_research_is_persisted_as_pending_review_and_cached():
    session = FakeSession()
    adapter = FakeProspectResearchAdapter(result())
    service = ProspectResearchService(session, adapter)
    tenant_id = uuid4()

    row, duplicate = await service.research(request(tenant_id=tenant_id), correlation_id="corr")
    cached, duplicate_again = await service.research(
        request(tenant_id=tenant_id), correlation_id="corr-2"
    )

    assert row.status == "PENDING_REVIEW"
    assert duplicate is False
    assert cached.id == row.id
    assert duplicate_again is True
    assert adapter.calls == 1
    assert any(getattr(item, "action", None) == "PROSPECT_RESEARCHED" for item in session.added)


@pytest.mark.asyncio
async def test_same_source_is_deduplicated_without_cross_tenant_data_leak():
    session = FakeSession()
    adapter = FakeProspectResearchAdapter(result())
    service = ProspectResearchService(session, adapter)
    tenant_a, tenant_b = uuid4(), uuid4()

    first, _ = await service.research(request(tenant_id=tenant_a), correlation_id="corr")
    same_source, cached = await service.research(
        request("research-2", tenant_id=tenant_a), correlation_id="corr"
    )
    other_tenant, other_cached = await service.research(
        request("research-3", tenant_id=tenant_b), correlation_id="corr"
    )

    assert same_source.id == first.id
    assert cached is True
    assert other_tenant.id != first.id
    assert other_cached is False
    assert adapter.calls == 2


@pytest.mark.asyncio
async def test_same_idempotency_key_with_another_source_is_rejected():
    session = FakeSession()
    adapter = FakeProspectResearchAdapter(result())
    service = ProspectResearchService(session, adapter)
    tenant_id = uuid4()
    await service.research(request(tenant_id=tenant_id), correlation_id="corr")
    changed = request(tenant_id=tenant_id).model_copy(update={"source_url": "https://other.example/"})

    with pytest.raises(ResearchIdempotencyConflict):
        await service.research(changed, correlation_id="corr")


@pytest.mark.asyncio
async def test_unavailable_source_creates_failed_safe_record():
    session = FakeSession()
    adapter = FakeProspectResearchAdapter(error=RuntimeError("network"))
    service = ProspectResearchService(session, adapter)

    row, duplicate = await service.research(request(), correlation_id="corr")

    assert duplicate is False
    assert row.status == "FAILED"
    assert row.failure_code == "RESEARCH_FAILED"
    assert row.result["company"] is None
