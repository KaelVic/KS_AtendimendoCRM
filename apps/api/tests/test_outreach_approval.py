from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import HttpUrl

from src.db.models import ProspectResearch
from src.integrations.whatsapp import SessionSnapshot, SessionStatus
from src.outreach.contracts import OutreachDraftCreate, OutreachEdit
from src.outreach.gateway import FakeColdOutreachGateway
from src.outreach.service import (
    ApprovalExpired,
    OutreachAlreadySent,
    OutreachNotAllowed,
    OutreachNotFound,
    OutreachService,
)
from src.prospecting.contracts import (
    BusinessContact,
    DigitalPresence,
    ProspectResearchResult,
    VerifiableFinding,
)


class FakeResult:
    rowcount = 1


class FakeSession:
    def __init__(self, research: ProspectResearch):
        self.research = research
        self.researches = [research]
        self.drafts = []
        self.added = []

    async def scalar(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        params = statement.compile().params
        tenant = next((v for k, v in params.items() if k.startswith("tenant_id")), None)
        if entity is ProspectResearch:
            research_id = next((v for k, v in params.items() if k.startswith("id")), None)
            return next(
                (
                    row
                    for row in self.researches
                    if row.tenant_id == tenant and row.id == research_id
                ),
                None,
            )
        for draft in self.drafts:
            if tenant != draft.tenant_id:
                continue
            if any(
                k.startswith("idempotency_key") and v == draft.idempotency_key
                for k, v in params.items()
            ):
                return draft
            if any(
                k.startswith("research_id") and v == draft.research_id for k, v in params.items()
            ):
                return draft
            recipient = next(
                (v for k, v in params.items() if k.startswith("recipient_ref")),
                None,
            )
            if recipient is not None:
                excluded_id = next(
                    (v for k, v in params.items() if k.startswith("id")),
                    None,
                )
                if draft.recipient_ref == recipient and draft.id != excluded_id:
                    return draft
                continue
            if any(k.startswith("id") and v == draft.id for k, v in params.items()):
                return draft
        return None

    def add(self, value):
        self.added.append(value)
        if value.__class__.__name__ == "OutreachDraft":
            self.drafts.append(value)

    async def commit(self):
        return None

    async def refresh(self, value):
        return None

    async def flush(self):
        return None

    async def execute(self, statement):
        return FakeResult()

    async def rollback(self):
        return None


def make_research(tenant_id):
    source = HttpUrl("https://clinic.example/")
    result = ProspectResearchResult(
        company="Clínica Exemplo",
        business_contact=BusinessContact(phone="+55 (11) 99999-9999", source_url=source),
        evidence_urls=[source],
        fetched_at=datetime.now(timezone.utc),
        digital_presence=DigitalPresence(website=True, instagram=True),
        findings=[
            VerifiableFinding(claim="O site publica contato empresarial.", evidence_url=source),
            VerifiableFinding(claim="O site possui presença digital pública.", evidence_url=source),
            VerifiableFinding(claim="O site apresenta serviços da clínica.", evidence_url=source),
        ],
    )
    now = datetime.now(timezone.utc)
    return ProspectResearch(
        id=uuid4(),
        tenant_id=tenant_id,
        idempotency_key="research-1",
        segment="ESTHETIC_CLINIC",
        source_url=str(source),
        source_fingerprint="source-hash",
        status="PENDING_REVIEW",
        result=result.model_dump(mode="json"),
        fetched_at=now,
        version=1,
        created_at=now,
        updated_at=now,
    )


def make_service():
    tenant = uuid4()
    session = FakeSession(make_research(tenant))
    gateway = FakeColdOutreachGateway(
        SessionSnapshot(
            tenant_id=tenant,
            session_id="pilot",
            owner_ref="owner",
            status=SessionStatus.CONNECTED,
            secure=True,
        )
    )
    return (
        tenant,
        session,
        gateway,
        OutreachService(session, gateway, approval_ttl=timedelta(hours=24)),
    )


def create_request(research_id):
    return OutreachDraftCreate(
        research_id=research_id,
        idempotency_key="outreach-1",
        draft_text="Olá! Posso enviar uma observação sobre o site da clínica?",
        approach_reason="Oferecer uma mini-auditoria gratuita e pedir permissão.",
    )


@pytest.mark.asyncio
async def test_queue_derives_company_source_findings_and_contact_from_research():
    tenant, session, _, service = make_service()

    draft, duplicate = await service.create(
        tenant, create_request(session.research.id), correlation_id="corr"
    )

    assert duplicate is False
    assert draft.status == "PENDING_APPROVAL"
    assert draft.company_name == "Clínica Exemplo"
    assert draft.source_url == "https://clinic.example/"
    assert len(draft.findings) == 3
    assert draft.recipient_ref == "5511999999999"


@pytest.mark.asyncio
async def test_send_requires_current_human_approval_and_is_idempotent():
    tenant, session, gateway, service = make_service()
    draft, _ = await service.create(
        tenant, create_request(session.research.id), correlation_id="corr"
    )

    with pytest.raises(OutreachNotAllowed, match="APPROVAL"):
        await service.send(tenant, draft.id, "send-1", correlation_id="corr")

    await service.approve(
        tenant, draft.id, confirmed=True, actor_user_id=None, correlation_id="corr"
    )
    sent, duplicate = await service.send(tenant, draft.id, "send-1", correlation_id="corr")
    same, duplicate_again = await service.send(tenant, draft.id, "send-1", correlation_id="corr")

    assert sent.status == "SENT"
    assert duplicate is False
    assert same.id == sent.id
    assert duplicate_again is True
    assert len(gateway.sent) == 1

    with pytest.raises(OutreachAlreadySent):
        await service.send(tenant, draft.id, "send-2", correlation_id="corr")


@pytest.mark.asyncio
async def test_edit_invalidates_approval_and_number_change_cannot_use_old_approval():
    tenant, session, _, service = make_service()
    draft, _ = await service.create(
        tenant, create_request(session.research.id), correlation_id="corr"
    )
    await service.approve(
        tenant, draft.id, confirmed=True, actor_user_id=None, correlation_id="corr"
    )

    await service.edit(
        tenant,
        draft.id,
        OutreachEdit(draft_text="Novo texto aprovado depois.", recipient_ref="5511888888888"),
        actor_user_id=None,
        correlation_id="corr",
    )

    with pytest.raises(OutreachNotAllowed, match="APPROVAL"):
        await service.send(tenant, draft.id, "send-1", correlation_id="corr")


@pytest.mark.asyncio
async def test_opt_out_after_approval_pauses_without_sending():
    tenant, session, gateway, service = make_service()
    draft, _ = await service.create(
        tenant, create_request(session.research.id), correlation_id="corr"
    )
    await service.approve(
        tenant, draft.id, confirmed=True, actor_user_id=None, correlation_id="corr"
    )
    await service.opt_out(tenant, draft.id, correlation_id="corr")

    with pytest.raises(OutreachNotAllowed, match="OPT_OUT"):
        await service.send(tenant, draft.id, "send-1", correlation_id="corr")
    assert not gateway.sent


@pytest.mark.asyncio
async def test_changed_research_data_expires_approval():
    tenant, session, _, service = make_service()
    draft, _ = await service.create(
        tenant, create_request(session.research.id), correlation_id="corr"
    )
    await service.approve(
        tenant, draft.id, confirmed=True, actor_user_id=None, correlation_id="corr"
    )
    session.research.result["company"] = "Outro nome"

    with pytest.raises(ApprovalExpired):
        await service.send(tenant, draft.id, "send-1", correlation_id="corr")
    assert session.drafts[0].status == "EXPIRED"


@pytest.mark.asyncio
async def test_edit_rejects_number_already_approached_in_same_tenant():
    tenant, session, _, service = make_service()
    first, _ = await service.create(
        tenant, create_request(session.research.id), correlation_id="corr"
    )

    second_research = make_research(tenant)
    second_research.id = uuid4()
    second_research.result["business_contact"]["phone"] = "+55 (11) 98888-8888"
    session.researches.append(second_research)
    second, _ = await service.create(
        tenant,
        create_request(second_research.id).model_copy(update={"idempotency_key": "outreach-2"}),
        correlation_id="corr",
    )

    with pytest.raises(OutreachNotAllowed, match="RECIPIENT_ALREADY_APPROACHED"):
        await service.edit(
            tenant,
            first.id,
            OutreachEdit(recipient_ref=second.recipient_ref),
            actor_user_id=None,
            correlation_id="corr",
        )
    assert first.recipient_ref != second.recipient_ref


@pytest.mark.asyncio
async def test_old_approval_expires_before_gateway_call():
    tenant, session, gateway, service = make_service()
    draft, _ = await service.create(
        tenant, create_request(session.research.id), correlation_id="corr"
    )
    await service.approve(
        tenant, draft.id, confirmed=True, actor_user_id=None, correlation_id="corr"
    )

    with pytest.raises(ApprovalExpired):
        await service.send(
            tenant,
            draft.id,
            "send-1",
            correlation_id="corr",
            now=draft.expires_at + timedelta(seconds=1),
        )
    assert not gateway.sent


@pytest.mark.asyncio
async def test_unsafe_session_pauses_draft_before_gateway_call():
    tenant, session, gateway, service = make_service()
    draft, _ = await service.create(
        tenant, create_request(session.research.id), correlation_id="corr"
    )
    await service.approve(
        tenant, draft.id, confirmed=True, actor_user_id=None, correlation_id="corr"
    )
    gateway._snapshot = gateway._snapshot.model_copy(update={"status": SessionStatus.DISCONNECTED})

    with pytest.raises(OutreachNotAllowed, match="SESSION_UNSAFE"):
        await service.send(tenant, draft.id, "send-1", correlation_id="corr")
    assert session.drafts[0].status == "PAUSED"
    assert session.drafts[0].pause_reason == "SESSION_UNSAFE_OR_DISCONNECTED"
    assert not gateway.sent


@pytest.mark.asyncio
async def test_same_recipient_cannot_receive_a_second_first_approach():
    tenant, session, _, service = make_service()
    draft, _ = await service.create(
        tenant, create_request(session.research.id), correlation_id="corr"
    )
    second_research = make_research(tenant)
    second_research.id = uuid4()
    session.researches.append(second_research)

    duplicate, is_duplicate = await service.create(
        tenant,
        create_request(second_research.id).model_copy(
            update={"idempotency_key": "outreach-2", "draft_text": "Outra primeira mensagem."}
        ),
        correlation_id="corr",
    )

    assert duplicate.id == draft.id
    assert is_duplicate is True


@pytest.mark.asyncio
async def test_draft_cannot_be_accessed_from_another_tenant():
    tenant, session, _, service = make_service()
    draft, _ = await service.create(
        tenant, create_request(session.research.id), correlation_id="corr"
    )

    with pytest.raises(OutreachNotFound):
        await service.send(uuid4(), draft.id, "send-1", correlation_id="corr")
