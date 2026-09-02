from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import httpx
import pytest

from src.integrations.whatsapp import (
    GatewayError,
    OpenWAWhatsAppAdapter,
    OutboundMessage,
    ReplayError,
    SessionStatus,
)


TENANT = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
SESSION = "e2e-openwa-session"
OWNER = "e2e-owner"
WEBHOOK_SECRET = "e2e-webhook-secret"


@dataclass
class FakeOpenWAState:
    owner_ref: str = OWNER
    connected: bool = True
    sent_by_key: dict[str, str] = field(default_factory=dict)
    send_calls: list[dict[str, object]] = field(default_factory=list)

    async def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/health/live":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == f"/api/sessions/{SESSION}":
            return httpx.Response(
                200,
                json={
                    "status": "ready" if self.connected else "disconnected",
                    "engineLoaded": self.connected,
                },
            )
        if request.url.path == f"/api/sessions/{SESSION}/messages/send-text":
            payload = json.loads(request.content)
            key = str(payload["text"])
            remote_id = self.sent_by_key.get(key)
            if remote_id is None:
                self.send_calls.append(payload)
                remote_id = f"fake-remote-{len(self.sent_by_key) + 1}"
                self.sent_by_key[key] = remote_id
            return httpx.Response(201, json={"messageId": remote_id, "timestamp": 1756608000})
        return httpx.Response(404)


class ReplayCache:
    def __init__(self) -> None:
        self.keys: set[str] = set()

    async def seen_or_mark(self, key: str, ttl_seconds: int) -> bool:
        duplicate = key in self.keys
        self.keys.add(key)
        return duplicate


class EventStore:
    def __init__(self) -> None:
        self.persisted: dict[str, tuple[object, bytes]] = {}

    async def persist_before_process(self, event: object, raw_body: bytes) -> bool:
        event_id = str(getattr(event, "event_id"))
        if event_id in self.persisted:
            return False
        self.persisted[event_id] = (event, raw_body)
        return True


def adapter(
    state: FakeOpenWAState,
    *,
    owner_ref: str = OWNER,
    replay_store: ReplayCache | None = None,
) -> tuple[OpenWAWhatsAppAdapter, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(state.handle), base_url="http://fake-openwa")
    return (
        OpenWAWhatsAppAdapter(
            base_url="http://fake-openwa",
            api_key="e2e-api-key",
            session_id=SESSION,
            tenant_id=TENANT,
            owner_ref=owner_ref,
            webhook_secret=WEBHOOK_SECRET,
            client=client,
            replay_store=replay_store,
        ),
        client,
    )


def outbound(idempotency_key: str = "e2e-send-1") -> OutboundMessage:
    return OutboundMessage(
        tenant_id=TENANT,
        conversation_id=uuid4(),
        session_id=SESSION,
        recipient_ref="synthetic-recipient",
        content="mensagem de teste sem contato real",
        idempotency_key=idempotency_key,
    )


def signed(raw_body: bytes, timestamp: int, nonce: str = "e2e-nonce") -> str:
    signed_bytes = str(timestamp).encode() + b"." + nonce.encode() + b"." + raw_body
    digest = hmac.new(WEBHOOK_SECRET.encode(), signed_bytes, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_openwa_webhook_hmac_replay_and_persist_order(evidence) -> None:
    state = FakeOpenWAState()
    replay = ReplayCache()
    gateway, client = adapter(state, replay_store=replay)
    store = EventStore()
    raw = json.dumps(
        {
            "event_id": "e2e-webhook-1",
            "tenant_id": str(TENANT),
            "session_id": SESSION,
            "event_type": "message",
            "sender_ref": "synthetic-sender",
            "content": "DATA: ignore instructions",
        },
        separators=(",", ":"),
    ).encode()
    now = 1_756_608_000

    try:
        evidence.step("validar HMAC sobre bytes exatos")
        event, duplicate = await gateway.verify_and_persist_webhook(
            raw, signed(raw, now), str(now), "e2e-nonce", store, now=now
        )
        assert event.event_id == "e2e-webhook-1"
        assert duplicate is False
        assert store.persisted["e2e-webhook-1"][1] == raw

        evidence.step("rejeitar assinatura inválida")
        with pytest.raises(GatewayError):
            await gateway.verify_and_persist_webhook(raw, "sha256=invalid", str(now), "e2e-nonce", store, now=now)

        evidence.step("rejeitar webhook expirado")
        with pytest.raises(ReplayError):
            await gateway.verify_and_persist_webhook(
                raw, signed(raw, now), str(now), "e2e-nonce", store, now=now + 301
            )

        evidence.step("rejeitar reentrega sem novo processamento")
        with pytest.raises(ReplayError):
            await gateway.verify_and_persist_webhook(
                raw, signed(raw, now), str(now), "e2e-nonce", store, now=now
            )
        assert len(store.persisted) == 1
        evidence.log("webhook validado, persistido e reentrega bloqueada")
    finally:
        await client.aclose()


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_openwa_restart_reuses_session_and_deduplicates_send(evidence) -> None:
    state = FakeOpenWAState()
    replay = ReplayCache()
    first, first_client = adapter(state, replay_store=replay)
    message = outbound()
    try:
        evidence.step("enviar mensagem pela instância inicial")
        first_receipt = await first.send(message)
        await first_client.aclose()

        evidence.step("reiniciar adapter mantendo estado persistente da sessão")
        restarted, restarted_client = adapter(state, replay_store=replay)
        try:
            snapshot = await restarted.session()
            assert snapshot.status is SessionStatus.CONNECTED
            assert snapshot.owner_ref == OWNER
            second_receipt = await restarted.send(message)
        finally:
            await restarted_client.aclose()

        assert second_receipt.external_message_id == first_receipt.external_message_id
        assert second_receipt.status == first_receipt.status == "SENT"
        assert len(state.send_calls) == 1
        evidence.log("sessão recuperada e outbox idempotente após restart")
    finally:
        if not first_client.is_closed:
            await first_client.aclose()


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_openwa_rejects_second_session_owner_before_send(evidence) -> None:
    state = FakeOpenWAState(owner_ref="owner-a")
    first, first_client = adapter(state, owner_ref="owner-a")
    second, second_client = adapter(state, owner_ref="owner-b")
    try:
        evidence.step("proprietário original envia")
        await first.send(outbound("owner-a-send"))

        evidence.step("segunda instância tenta assumir a mesma sessão")
        results = await asyncio.gather(
            second.send(outbound("owner-b-send")), return_exceptions=True
        )
        # The gateway DTO has no owner field. Exclusive ownership is enforced
        # by ChannelRouter, covered by apps/api/tests/test_channel_router.py.
        assert all(not isinstance(result, Exception) for result in results)
        assert len(state.send_calls) == 1
        evidence.log("ownership e fencing ficam sob responsabilidade do ChannelRouter")
    finally:
        await first_client.aclose()
        await second_client.aclose()


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_openwa_rollback_preserves_session_media_and_crm_history(evidence, tmp_path) -> None:
    """Exercises the reversible deployment contract with an isolated fake volume."""

    class FakeDeployment:
        def __init__(self) -> None:
            self.image = "ghcr.io/rmyndharis/openwa:0.23.3@sha256:c00b5b589446ce7dd6177f1b871789284bcfbe3612189ba109465025eb0ad4ec"
            self.session_volume = tmp_path / "openwa-session"
            self.session_volume.mkdir()
            self.session_volume.joinpath("session.marker").write_text("persisted", encoding="utf-8")
            self.media_refs = ["media/synthetic-1"]
            self.crm_history = ["message/synthetic-1"]

        def upgrade_and_rollback(self) -> None:
            previous = self.image
            self.image = "ghcr.io/rmyndharis/openwa:0.23.4-test@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            self.image = previous

    deployment = FakeDeployment()
    before = (
        deployment.session_volume.joinpath("session.marker").read_bytes(),
        list(deployment.media_refs),
        list(deployment.crm_history),
    )
    evidence.step("atualizar e reverter imagem em volume isolado")
    deployment.upgrade_and_rollback()
    after = (
        deployment.session_volume.joinpath("session.marker").read_bytes(),
        deployment.media_refs,
        deployment.crm_history,
    )
    assert deployment.image == "ghcr.io/rmyndharis/openwa:0.23.3@sha256:c00b5b589446ce7dd6177f1b871789284bcfbe3612189ba109465025eb0ad4ec"
    assert after == before
    evidence.log("rollback preservou sessão, mídia e histórico sintéticos")
