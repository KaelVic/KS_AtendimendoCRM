import hashlib
import hmac
import json
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from src.integrations.whatsapp import (
    FakeWhatsAppGateway,
    GatewayError,
    MediaKind,
    MediaRef,
    OpenWAWhatsAppAdapter,
    OutboundMessage,
    ReplayError,
    SessionSnapshot,
    SessionStatus,
    UnsafeSessionError,
    MAX_WEBHOOK_PAYLOAD_BYTES,
)

TENANT = uuid4()
SESSION = "pilot-session"
TEST_WEBHOOK_SECRET = b"TEST_ONLY_WEBHOOK_SECRET"


def outbound(**changes):
    data = {"tenant_id": TENANT, "conversation_id": uuid4(), "session_id": SESSION, "recipient_ref": "5511999999999", "content": "olá", "idempotency_key": "idem-1"}
    data.update(changes)
    return OutboundMessage(**data)


def snapshot(**changes):
    data = {"tenant_id": TENANT, "session_id": SESSION, "owner_ref": "owner-ref", "status": SessionStatus.CONNECTED, "secure": True}
    data.update(changes)
    return SessionSnapshot(**data)


class ReplayCache:
    def __init__(self): self.keys = set()
    async def seen_or_mark(self, key, ttl_seconds):
        duplicate = key in self.keys
        self.keys.add(key)
        return duplicate


class EventStore:
    def __init__(self):
        self.events = {}

    async def persist_before_process(self, event, raw_body):
        if event.event_id in self.events:
            return False
        self.events[event.event_id] = (event, raw_body)
        return True


def signed(payload: bytes, timestamp: int = 1_756_608_000, nonce: str = "nonce-1") -> tuple[str, str, str]:
    timestamp_text = str(timestamp)
    signed_bytes = timestamp_text.encode() + b"." + nonce.encode() + b"." + payload
    signature = hmac.new(TEST_WEBHOOK_SECRET, signed_bytes, hashlib.sha256).hexdigest()
    return f"sha256={signature}", timestamp_text, nonce


@pytest.mark.asyncio
async def test_fake_gateway_sends_idempotently_and_blocks_unsafe_session():
    gateway = FakeWhatsAppGateway(snapshot())
    first = await gateway.send(outbound())
    second = await gateway.send(outbound())
    assert first == second
    with pytest.raises(UnsafeSessionError):
        await gateway.send(outbound(tenant_id=uuid4()))
    with pytest.raises(UnsafeSessionError):
        await FakeWhatsAppGateway(snapshot(status=SessionStatus.DISCONNECTED)).send(outbound())
    with pytest.raises(UnsafeSessionError):
        await gateway.send(outbound(control_state="HUMAN_ACTIVE"))


def test_media_contract_allows_only_supported_types_and_size():
    assert MediaRef(kind=MediaKind.IMAGE, mime_type="image/jpeg", size_bytes=10, storage_ref="s3://opaque-ref")
    assert MediaRef(kind=MediaKind.AUDIO, mime_type="audio/ogg", size_bytes=10, storage_ref="opaque-audio")
    assert MediaRef(kind=MediaKind.DOCUMENT, mime_type="application/pdf", size_bytes=10, storage_ref="opaque-pdf")
    with pytest.raises(ValidationError):
        MediaRef(kind=MediaKind.DOCUMENT, mime_type="text/html", size_bytes=10, storage_ref="unsafe")
    with pytest.raises(ValidationError):
        outbound(content=None, media=None)


@pytest.mark.asyncio
async def test_hmac_uses_exact_bytes_persists_before_processing_and_rejects_replay():
    event = {"event_id": "evt-1", "tenant_id": str(TENANT), "session_id": SESSION, "event_type": "message", "sender_ref": "opaque-sender", "content": "DATA"}
    raw = json.dumps(event, separators=(",", ":")).encode()
    signature, timestamp, nonce = signed(raw)
    adapter = OpenWAWhatsAppAdapter(base_url="http://openwa", api_key="TEST_ONLY_API_KEY", session_id=SESSION, tenant_id=TENANT, owner_ref="owner-ref", webhook_secret=TEST_WEBHOOK_SECRET.decode(), replay_store=ReplayCache())
    store = EventStore()
    parsed, duplicate = await adapter.verify_and_persist_webhook(raw, signature, timestamp, nonce, store, now=1_756_608_000)
    assert parsed.event_id == "evt-1"
    assert duplicate is False
    with pytest.raises(ReplayError):
        await adapter.verify_and_persist_webhook(raw, signature, timestamp, nonce, store, now=1_756_608_000)
    altered = raw.replace(b"DATA", b"data")
    with pytest.raises(GatewayError):
        await adapter.verify_and_persist_webhook(altered, signature, timestamp, nonce, store, now=1_756_608_000)


@pytest.mark.asyncio
async def test_hmac_rejects_invalid_and_expired_webhooks():
    raw = json.dumps({"event_id": "evt-2", "tenant_id": str(TENANT), "session_id": SESSION, "event_type": "receipt", "sender_ref": "x"}).encode()
    signature, timestamp, nonce = signed(raw, nonce="nonce-2")
    adapter = OpenWAWhatsAppAdapter(base_url="http://openwa", api_key="TEST_ONLY_API_KEY", session_id=SESSION, tenant_id=TENANT, owner_ref="owner-ref", webhook_secret=TEST_WEBHOOK_SECRET.decode())
    with pytest.raises(GatewayError):
        await adapter.verify_and_persist_webhook(raw, "sha256=invalid", timestamp, nonce, EventStore(), now=1_756_608_000)
    with pytest.raises(ReplayError):
        await adapter.verify_and_persist_webhook(raw, signature, timestamp, nonce, EventStore(), now=1_756_608_500)


@pytest.mark.asyncio
async def test_hmac_binds_timestamp_and_rejects_invalid_nonce():
    raw = b'{"event_id":"evt-3","tenant_id":"ignored","session_id":"ignored","event_type":"message","sender_ref":"sender"}'
    signature, timestamp, nonce = signed(raw, nonce="nonce-3")
    adapter = OpenWAWhatsAppAdapter(base_url="http://openwa", api_key="TEST_ONLY_API_KEY", session_id=SESSION, tenant_id=TENANT, owner_ref="owner-ref", webhook_secret=TEST_WEBHOOK_SECRET.decode())
    with pytest.raises(GatewayError):
        await adapter.verify_and_persist_webhook(raw, signature, str(int(timestamp) + 1), nonce, EventStore(), now=1_756_608_000)
    with pytest.raises(ReplayError):
        await adapter.verify_and_persist_webhook(raw, signature, timestamp, "nonce with spaces", EventStore(), now=1_756_608_000)


@pytest.mark.asyncio
async def test_webhook_payload_limit_is_enforced_before_parsing():
    raw = b"x" * (MAX_WEBHOOK_PAYLOAD_BYTES + 1)
    adapter = OpenWAWhatsAppAdapter(
        base_url="http://openwa",
        api_key="TEST_ONLY_API_KEY",
        session_id=SESSION,
        tenant_id=TENANT,
        owner_ref="owner-ref",
        webhook_secret=TEST_WEBHOOK_SECRET.decode(),
        replay_store=ReplayCache(),
    )

    with pytest.raises(GatewayError, match="payload de webhook"):
        await adapter.verify_and_persist_webhook(
            raw,
            "sha256=not-checked",
            "1756608000",
            "nonce-limit",
            EventStore(),
            now=1_756_608_000,
        )


@pytest.mark.asyncio
async def test_openwa_send_uses_official_contract_and_maps_receipt_without_logging_payload():
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(201, json={"messageId": "external-1", "timestamp": 1756608000})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenWAWhatsAppAdapter(base_url="http://openwa", api_key="TEST_ONLY_API_KEY", session_id=SESSION, tenant_id=TENANT, owner_ref="owner-ref", webhook_secret=TEST_WEBHOOK_SECRET.decode(), client=client)
        async def connected_session():
            return snapshot()
        adapter.session = connected_session  # type: ignore[method-assign]
        receipt = await adapter.send(outbound())
    assert receipt.external_message_id == "external-1"
    assert len(calls) == 1
    assert calls[0].url.path == f"/api/sessions/{SESSION}/messages/send-text"
    assert calls[0].headers["x-api-key"] == "TEST_ONLY_API_KEY"
    assert json.loads(calls[0].content) == {"chatId": "5511999999999", "text": outbound().content}


@pytest.mark.asyncio
async def test_openwa_timeout_retries_at_most_twice_then_fails_closed():
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout("test timeout")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenWAWhatsAppAdapter(base_url="http://openwa", api_key="TEST_ONLY_API_KEY", session_id=SESSION, tenant_id=TENANT, owner_ref="owner-ref", webhook_secret=TEST_WEBHOOK_SECRET.decode(), client=client)
        with pytest.raises(GatewayError):
            await adapter.health()
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_session_reports_remote_owner_and_reconnect_state_without_exposing_credentials():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "qr_ready", "engineLoaded": False})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenWAWhatsAppAdapter(base_url="http://openwa", api_key="TEST_ONLY_API_KEY", session_id=SESSION, tenant_id=TENANT, owner_ref="owner-ref", webhook_secret=TEST_WEBHOOK_SECRET.decode(), client=client)
        current = await adapter.session()
    assert current.status is SessionStatus.QR_REQUIRED
    assert current.secure is False
    assert current.owner_ref == "owner-ref"


@pytest.mark.asyncio
async def test_openwa_does_not_send_when_owner_or_controlled_session_changes():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"state": "CONNECTED"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenWAWhatsAppAdapter(base_url="http://openwa", api_key="TEST_ONLY_API_KEY", session_id=SESSION, tenant_id=TENANT, owner_ref="owner-ref", webhook_secret=TEST_WEBHOOK_SECRET.decode(), client=client)
        async def other_owner_session():
            return snapshot(owner_ref="other-owner")
        adapter.session = other_owner_session  # type: ignore[method-assign]
        with pytest.raises(UnsafeSessionError):
            await adapter.send(outbound())


@pytest.mark.asyncio
async def test_official_webhook_signature_uses_exact_body_and_event_id_deduplication():
    raw = json.dumps(
        {"event": "message", "data": {"id": "evt-official", "from": "5511999999999@c.us", "body": "hello"}},
        separators=(",", ":"),
    ).encode()
    signature = "sha256=" + hmac.new(TEST_WEBHOOK_SECRET, raw, hashlib.sha256).hexdigest()
    adapter = OpenWAWhatsAppAdapter(
        base_url="http://openwa",
        api_key="TEST_ONLY_API_KEY",
        session_id=SESSION,
        tenant_id=TENANT,
        owner_ref="owner-ref",
        webhook_secret=TEST_WEBHOOK_SECRET.decode(),
    )
    store = EventStore()

    parsed, duplicate = await adapter.verify_and_persist_webhook(raw, signature, event_store=store)

    assert parsed.external_message_id == "evt-official"
    assert parsed.sender_ref == "5511999999999@c.us"
    assert duplicate is False


@pytest.mark.asyncio
async def test_media_send_maps_to_official_endpoint_and_payload():
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(201, json={"messageId": "media-1", "timestamp": 1756608000})

    media = MediaRef(
        kind=MediaKind.IMAGE,
        mime_type="image/jpeg",
        size_bytes=10,
        storage_ref="https://storage.invalid/synthetic.jpg",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OpenWAWhatsAppAdapter(
            base_url="http://openwa",
            api_key="TEST_ONLY_API_KEY",
            session_id=SESSION,
            tenant_id=TENANT,
            owner_ref="owner-ref",
            webhook_secret=TEST_WEBHOOK_SECRET.decode(),
            client=client,
        )
        async def connected_session():
            return snapshot()
        adapter.session = connected_session  # type: ignore[method-assign]
        receipt = await adapter.send(outbound(content="legenda", media=media))

    assert receipt.external_message_id == "media-1"
    assert calls[0].url.path == f"/api/sessions/{SESSION}/messages/send-image"
    assert json.loads(calls[0].content) == {
        "chatId": "5511999999999",
        "url": "https://storage.invalid/synthetic.jpg",
        "mimetype": "image/jpeg",
        "caption": "legenda",
    }
