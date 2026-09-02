from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest

from src.db.models import Conversation, ProposalItem
from src.proposals.contracts import ProposalCreateRequest
from src.proposals.renderer import ProposalPdfRenderer
from src.proposals.service import ProposalIdempotencyConflict, ProposalService
from src.proposals.storage import ProposalStorage
from src.proposals.contracts import ProposalDraft, ProposalLineDraft


class FakeSession:
    def __init__(self, conversation, existing=None):
        self.conversation = conversation
        self.existing = existing
        self.added = []
        self.commits = 0

    async def scalar(self, statement):
        text = str(statement)
        if "conversations" in text:
            return self.conversation
        return self.existing

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commits += 1

    async def refresh(self, value):
        return None

    async def rollback(self):
        return None


def request(tenant_id, conversation_id, **updates):
    draft = ProposalDraft(
        customer="Clínica Exemplo",
        need="Melhorar a presença digital.",
        product_id="site-essencial",
        items=[ProposalLineDraft(product_id="site-essencial", quantity=1)],
        price_cents=99700,
        delivery_days=3,
        revisions=2,
        scope="até 3 páginas",
    ).model_copy(update=updates.pop("draft", {}))
    return ProposalCreateRequest(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        idempotency_key=updates.pop("idempotency_key", "proposal-1"),
        draft=draft,
    )


@pytest.mark.asyncio
async def test_service_renders_persists_snapshot_items_and_audit(tmp_path: Path):
    tenant_id, conversation_id = uuid4(), uuid4()
    conversation = Conversation(id=conversation_id, tenant_id=tenant_id)
    session = FakeSession(conversation)
    service = ProposalService(session, ProposalStorage(tmp_path))

    proposal, duplicate, validated = await service.create(
        request(tenant_id, conversation_id),
        correlation_id=str(uuid4()),
        generated_on=date(2026, 8, 31),
    )

    assert duplicate is False
    assert validated.renderable is True
    assert proposal.status == "RENDERED"
    assert proposal.pdf_sha256 == ProposalPdfRenderer.sha256(
        (tmp_path / "proposals" / str(tenant_id) / f"{proposal.data_hash}.pdf").read_bytes()
    )
    assert any(isinstance(value, ProposalItem) for value in session.added)
    assert any(value.__class__.__name__ == "AuditEvent" for value in session.added)
    assert session.commits == 1


@pytest.mark.asyncio
async def test_service_requires_approval_and_does_not_create_pdf_for_adultered_draft(
    tmp_path: Path,
):
    tenant_id, conversation_id = uuid4(), uuid4()
    session = FakeSession(Conversation(id=conversation_id, tenant_id=tenant_id))
    service = ProposalService(session, ProposalStorage(tmp_path))
    payload = request(
        tenant_id,
        conversation_id,
        draft={"price_cents": 1, "additional_scope": "fazer qualquer coisa"},
    )

    proposal, _, validated = await service.create(payload, correlation_id=str(uuid4()))

    assert validated.renderable is False
    assert proposal.status == "HUMAN_APPROVAL_REQUIRED"
    assert proposal.pdf_sha256 is None
    assert proposal.pdf_storage_key is None
    assert list(tmp_path.rglob("*.pdf")) == []


@pytest.mark.asyncio
async def test_service_reuses_identical_request_but_rejects_key_reuse_with_other_data(
    tmp_path: Path,
):
    tenant_id, conversation_id = uuid4(), uuid4()
    payload = request(tenant_id, conversation_id)
    first_session = FakeSession(Conversation(id=conversation_id, tenant_id=tenant_id))
    service = ProposalService(first_session, ProposalStorage(tmp_path))
    first, _, _ = await service.create(payload, correlation_id=str(uuid4()))

    duplicate_session = FakeSession(
        Conversation(id=conversation_id, tenant_id=tenant_id), existing=first
    )
    duplicate, is_duplicate, _ = await ProposalService(
        duplicate_session, ProposalStorage(tmp_path)
    ).create(payload, correlation_id=str(uuid4()))
    assert duplicate.id == first.id
    assert is_duplicate is True
    assert duplicate_session.commits == 0

    altered = payload.model_copy(
        update={"draft": payload.draft.model_copy(update={"price_cents": 1})}
    )
    with pytest.raises(ProposalIdempotencyConflict):
        await ProposalService(duplicate_session, ProposalStorage(tmp_path)).create(
            altered, correlation_id=str(uuid4())
        )
