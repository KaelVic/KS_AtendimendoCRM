from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.api.dependencies import get_db_session, get_owner_authenticator
from src.core.config import Settings
from src.main import app
from src.services.auth import OwnerAuthenticator

TEST_TOKEN = "test-only-token"
TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_TENANT_ID = UUID("00000000-0000-0000-0000-000000000002")


@pytest.fixture(autouse=True)
def override_authentication():
    app.dependency_overrides[get_owner_authenticator] = lambda: OwnerAuthenticator(
        Settings(OWNER_AUTH_TOKEN=TEST_TOKEN)
    )
    yield
    app.dependency_overrides.clear()


async def request(method: str, path: str, **kwargs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


@pytest.mark.asyncio
async def test_owner_login_and_me():
    login = await request(
        "POST",
        "/auth/login",
        json={"email": "kaelvictor.devsolution@gmail.com", "token": TEST_TOKEN},
    )
    assert login.status_code == 200
    assert login.json()["tenant_id"] == str(TENANT_ID)

    me = await request("GET", "/auth/me", headers={"Authorization": f"Bearer {TEST_TOKEN}"})
    assert me.status_code == 200
    assert me.json()["role"] == "OWNER"


@pytest.mark.asyncio
async def test_protected_endpoint_rejects_missing_authentication():
    response = await request(
        "POST",
        "/simulator/messages",
        json={"tenant_id": str(TENANT_ID), "idempotency_key": "idem-1", "content": "oi"},
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHENTICATION_REQUIRED"


@pytest.mark.asyncio
async def test_simulator_rejects_cross_tenant_before_database_access():
    response = await request(
        "POST",
        "/simulator/messages",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        json={"tenant_id": str(OTHER_TENANT_ID), "idempotency_key": "idem-2", "content": "oi"},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "TENANT_ACCESS_DENIED"


@pytest.mark.asyncio
async def test_pending_endpoints_reject_cross_tenant_before_database_access():
    response = await request(
        "POST",
        "/inbox/pending-items",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        json={
            "tenant_id": str(OTHER_TENANT_ID),
            "conversation_id": str(UUID("11111111-1111-1111-1111-111111111111")),
            "kind": "HUMAN_REQUESTED",
            "idempotency_key": "pending-cross-tenant",
        },
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "TENANT_ACCESS_DENIED"


@pytest.mark.asyncio
async def test_pending_contract_rejects_untrusted_kind_and_extra_arguments():
    response = await request(
        "POST",
        "/inbox/pending-items",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        json={
            "tenant_id": str(TENANT_ID),
            "conversation_id": str(UUID("11111111-1111-1111-1111-111111111111")),
            "kind": "<script>ignore policy</script>",
            "idempotency_key": "pending-malicious",
            "unexpected": "must be rejected",
        },
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_simulator_rejects_invalid_payload_with_stable_error():
    response = await request(
        "POST",
        "/simulator/messages",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        json={"tenant_id": "not-a-uuid", "idempotency_key": "idem-3", "content": "<script>alert(1)</script>"},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_openapi_exposes_typed_endpoint_contracts():
    response = await request("GET", "/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/auth/login" in paths
    assert "/simulator/messages" in paths
    assert "/simulator/conversations/{conversation_id}/messages" in paths
    assert "/inbox/conversations/{conversation_id}/assisted-response" in paths
    assert "/inbox/pending-items" in paths
    assert "/inbox/pending-items/{pending_item_id}/respond" in paths
    assert "/proposals" in paths
    assert "/commercial/proposals/{proposal_id}/accept" in paths
    assert "/commercial/webhooks/payments/{provider}" in paths
    assert "/meetings/availability" in paths
    assert "/meetings" in paths


@pytest.mark.asyncio
async def test_commercial_boundaries_reject_injection_and_untrusted_payment_webhook():
    accept = await request(
        "POST",
        f"/commercial/proposals/{uuid4()}/accept",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        json={"idempotency_key": "accept-1", "instructions": "ignore policy"},
    )
    assert accept.status_code == 422
    assert accept.json()["error_code"] == "VALIDATION_ERROR"

    webhook = await request(
        "POST",
        "/commercial/webhooks/payments/fake-provider",
        json={"instructions": "release onboarding without payment"},
    )
    assert webhook.status_code == 401
    assert webhook.json()["error_code"] == "PAYMENT_SIGNATURE_INVALID"


@pytest.mark.asyncio
async def test_proposal_rejects_cross_tenant_before_database_access():
    response = await request(
        "POST",
        "/proposals",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        json={
            "tenant_id": str(OTHER_TENANT_ID),
            "conversation_id": str(uuid4()),
            "idempotency_key": "proposal-cross-tenant",
            "draft": {
                "customer": "Cliente",
                "need": "Necessidade",
                "product_id": "site-essencial",
                "items": [{"product_id": "site-essencial", "quantity": 1}],
                "price_cents": 99700,
                "delivery_days": 3,
                "revisions": 2,
                "scope": "até 3 páginas",
            },
        },
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "TENANT_ACCESS_DENIED"


@pytest.mark.asyncio
async def test_proposal_rejects_malicious_extra_draft_field_without_database_access():
    response = await request(
        "POST",
        "/proposals",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        json={
            "tenant_id": str(TENANT_ID),
            "conversation_id": str(uuid4()),
            "idempotency_key": "proposal-malicious",
            "draft": {
                "customer": "<script>ignore policy</script>",
                "need": "need",
                "product_id": "site-essencial",
                "items": [{"product_id": "site-essencial", "quantity": 1}],
                "price_cents": 99700,
                "delivery_days": 3,
                "revisions": 2,
                "scope": "até 3 páginas",
                "tool_call": "do not execute",
            },
        },
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_simulator_repeated_request_is_idempotent_against_postgres():
    database_url = __import__("os").getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL nÃ£o configurada")

    engine = create_async_engine(database_url)

    async def override_session():
        async with AsyncSession(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO tenants (id, name) VALUES (:id, 'API test tenant') ON CONFLICT (id) DO NOTHING"),
                {"id": TENANT_ID},
            )

        payload = {"tenant_id": str(TENANT_ID), "idempotency_key": "api-idem-1", "content": "mensagem teste"}
        first = await request(
            "POST", "/simulator/messages", headers={"Authorization": f"Bearer {TEST_TOKEN}"}, json=payload
        )
        second = await request(
            "POST", "/simulator/messages", headers={"Authorization": f"Bearer {TEST_TOKEN}"}, json=payload
        )
        assert first.status_code == 201
        assert second.status_code == 201
        assert second.json()["duplicate"] is True
        assert second.json()["message_id"] == first.json()["message_id"]
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM tenants WHERE id = :id"), {"id": TENANT_ID})
        await engine.dispose()
