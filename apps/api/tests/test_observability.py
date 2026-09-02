from __future__ import annotations

import pytest
import hashlib
import hmac
import json
from uuid import uuid4
from httpx import ASGITransport, AsyncClient

from src.core.observability import metrics, record_tool_result
from src.integrations.whatsapp import InboundEvent, OpenWAWhatsAppAdapter, OutboundMessage
from src.main import app


@pytest.fixture(autouse=True)
def reset_metrics() -> None:
    metrics.reset()


def test_metrics_render_bounded_latency_and_tool_success_without_payload() -> None:
    metrics.inc("ks_duplicates_total", labels={"kind": "webhook", "provider": "openwa"})
    metrics.observe_latency("http", 6)
    metrics.observe_latency("http", 9)
    metrics.observe_latency("http", 24.9)
    record_tool_result("calendar.create", True)

    rendered = metrics.render()

    assert "ks_operation_latency_ms_p50{operation=\"http\"} 9" in rendered
    assert "ks_operation_latency_ms_p95{operation=\"http\"} 24.9" in rendered
    assert 'ks_tool_success_total{success="true",tool="calendar.create"} 1' in rendered
    assert "secret" not in rendered.lower()
    assert "message body" not in rendered.lower()


@pytest.mark.asyncio
async def test_metrics_endpoint_and_readiness_contract() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        metrics_response = await client.get("/metrics")
        readiness_response = await client.get("/health/ready")

    assert metrics_response.status_code == 200
    assert metrics_response.headers["content-type"].startswith("text/plain")
    assert readiness_response.status_code in {200, 503}
    components = readiness_response.json()["components"]
    assert {"postgres", "redis", "worker", "gemini", "openwa", "whatsapp_session", "email", "calendar"} <= set(components)


@pytest.mark.asyncio
async def test_webhook_correlation_id_can_be_carried_to_outbound_payload() -> None:
    tenant_id = uuid4()
    secret = b"test-webhook-secret"
    timestamp = "1756608000"
    raw = json.dumps(
        {
            "event_id": "observability-event",
            "tenant_id": str(tenant_id),
            "session_id": "session-observability",
            "event_type": "message",
            "sender_ref": "opaque-sender",
            "content": "DATA",
        }
    ).encode()
    nonce = "observability-nonce"
    signed_bytes = timestamp.encode() + b"." + nonce.encode() + b"." + raw
    signature = "sha256=" + hmac.new(secret, signed_bytes, hashlib.sha256).hexdigest()

    class Store:
        async def persist_before_process(self, event: InboundEvent, raw_body: bytes) -> bool:
            return True

    adapter = OpenWAWhatsAppAdapter(
        base_url="http://openwa",
        api_key="test-api-key",
        session_id="session-observability",
        tenant_id=tenant_id,
        owner_ref="owner",
        webhook_secret=secret.decode(),
    )
    event, duplicate = await adapter.verify_and_persist_webhook(
        raw, signature, timestamp, nonce, Store(), now=1_756_608_000
    )
    outbound = OutboundMessage(
        tenant_id=tenant_id,
        conversation_id=uuid4(),
        session_id="session-observability",
        recipient_ref="opaque-recipient",
        content="safe response",
        idempotency_key="outbound-idem",
        correlation_id=event.correlation_id,
    )

    assert duplicate is False
    assert event.correlation_id
    assert outbound.correlation_id == event.correlation_id
