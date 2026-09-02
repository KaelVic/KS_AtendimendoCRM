from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from src.api import outreach as outreach_api
from src.api.dependencies import get_db_session, get_owner_authenticator
from src.core.config import Settings
from src.integrations.whatsapp import SessionSnapshot, SessionStatus
from src.main import app
from src.outreach.gateway import FakeColdOutreachGateway
from src.outreach.service import OutreachService
from src.services.auth import OwnerAuthenticator

from test_outreach_approval import FakeSession, create_request, make_research


TEST_TOKEN = "test-only-token"
TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def outreach_http_context(monkeypatch: pytest.MonkeyPatch):
    session = FakeSession(make_research(TENANT_ID))
    gateway = FakeColdOutreachGateway(
        SessionSnapshot(
            tenant_id=TENANT_ID,
            session_id="pilot",
            owner_ref="owner",
            status=SessionStatus.CONNECTED,
            secure=True,
        )
    )

    async def override_db_session():
        yield session

    app.dependency_overrides[get_owner_authenticator] = lambda: OwnerAuthenticator(
        Settings(OWNER_AUTH_TOKEN=TEST_TOKEN)
    )
    app.dependency_overrides[get_db_session] = override_db_session
    monkeypatch.setattr(
        outreach_api,
        "get_settings",
        lambda: Settings(
            OUTREACH_PROVIDER="fake",
            OUTREACH_APPROVAL_TTL_HOURS=24,
            OUTREACH_DAILY_LIMIT=5,
            OUTREACH_MIN_INTERVAL_SECONDS=0,
        ),
    )
    monkeypatch.setattr(
        outreach_api,
        "_policy",
        outreach_api.ConservativeOutreachPolicy(daily_limit=5, minimum_interval=timedelta(0)),
    )
    monkeypatch.setattr(
        outreach_api,
        "_service",
        lambda owner, db: OutreachService(
            db,
            gateway,
            approval_ttl=timedelta(hours=24),
            policy=outreach_api._policy,
        ),
    )
    yield session, gateway
    app.dependency_overrides.clear()


async def request(method: str, path: str, **kwargs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


@pytest.mark.asyncio
async def test_outreach_requires_owner_authentication():
    response = await request(
        "POST",
        "/outreach/drafts",
        json={
            "research_id": str(UUID(int=1)),
            "idempotency_key": "x",
            "draft_text": "oi",
            "approach_reason": "auditoria",
        },
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHENTICATION_REQUIRED"


@pytest.mark.asyncio
async def test_frontend_tenant_field_is_rejected_and_valid_request_uses_token_tenant(
    outreach_http_context,
):
    session, _ = outreach_http_context
    headers = {"Authorization": f"Bearer {TEST_TOKEN}", "X-Tenant-ID": str(UUID(int=2))}
    payload = {
        "research_id": str(session.research.id),
        "idempotency_key": "http-outreach-1",
        "draft_text": "Olá! Posso enviar uma mini-auditoria?",
        "approach_reason": "Oferecer observações verificáveis.",
        "tenant_id": str(UUID(int=2)),
    }

    rejected = await request("POST", "/outreach/drafts", headers=headers, json=payload)
    assert rejected.status_code == 422
    assert rejected.json()["error_code"] == "VALIDATION_ERROR"

    payload.pop("tenant_id")
    created = await request("POST", "/outreach/drafts", headers=headers, json=payload)
    assert created.status_code == 201
    assert created.json()["tenant_id"] == str(TENANT_ID)
    assert created.json()["company"] == "Clínica Exemplo"
    assert len(created.json()["findings"]) == 3


@pytest.mark.asyncio
async def test_direct_send_endpoint_cannot_bypass_human_approval(outreach_http_context):
    session, gateway = outreach_http_context
    headers = {"Authorization": f"Bearer {TEST_TOKEN}"}
    payload = create_request(session.research.id).model_dump(mode="json")
    payload["idempotency_key"] = "http-outreach-2"
    created = await request("POST", "/outreach/drafts", headers=headers, json=payload)
    draft_id = created.json()["id"]

    response = await request(
        "POST",
        f"/outreach/drafts/{draft_id}/send",
        headers=headers,
        json={"idempotency_key": "http-send-1"},
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "APPROVAL_REQUIRED"
    assert gateway.sent == {}
