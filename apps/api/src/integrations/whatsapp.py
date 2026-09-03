import asyncio
import hashlib
import hmac
import json
import logging
import re
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Literal, Protocol
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from ..core.observability import metrics, record_integration

logger = logging.getLogger("ks_whatsapp")
OPENWA_VERSION = "v0.23.3"
MAX_WEBHOOK_AGE_SECONDS = 300
MAX_WEBHOOK_NONCE_LENGTH = 128
MAX_WEBHOOK_PAYLOAD_BYTES = 1 * 1024 * 1024
MAX_MEDIA_BYTES = 25 * 1024 * 1024
MAX_OPENWA_TEXT_BYTES = 4096


class GatewayError(RuntimeError):
    pass


class UnsafeSessionError(GatewayError):
    pass


class ReplayError(GatewayError):
    pass


class SessionStatus(str, Enum):
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    QR_REQUIRED = "QR_REQUIRED"
    RELINK_REQUIRED = "RELINK_REQUIRED"
    ERROR = "ERROR"


class MediaKind(str, Enum):
    IMAGE = "IMAGE"
    AUDIO = "AUDIO"
    DOCUMENT = "DOCUMENT"


class MediaRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: MediaKind
    mime_type: str = Field(min_length=1, max_length=120)
    size_bytes: int = Field(gt=0, le=MAX_MEDIA_BYTES)
    storage_ref: str = Field(min_length=1, max_length=500)

    @field_validator("mime_type")
    @classmethod
    def allowlisted_mime(cls, value: str) -> str:
        allowed = ("image/", "audio/", "application/pdf")
        if not value.lower().startswith(allowed):
            raise ValueError("MIME não permitido")
        return value


class SessionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    session_id: str = Field(min_length=1, max_length=255)
    owner_ref: str | None = Field(default=None, max_length=255)
    status: SessionStatus
    version: str = OPENWA_VERSION
    secure: bool = False


class InboundEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=255)
    tenant_id: UUID
    session_id: str = Field(min_length=1, max_length=255)
    event_type: str = Field(min_length=1, max_length=64)
    external_message_id: str | None = Field(default=None, max_length=255)
    sender_ref: str = Field(min_length=1, max_length=255)
    content: str | None = Field(default=None, max_length=20_000)
    media: MediaRef | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str | None = Field(default=None, min_length=1, max_length=64)


class OutboundMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    conversation_id: UUID
    session_id: str = Field(min_length=1, max_length=255)
    recipient_ref: str = Field(min_length=1, max_length=255)
    recipient_contact_id: UUID | None = None
    content: str | None = Field(default=None, max_length=20_000)
    media: MediaRef | None = None
    idempotency_key: str = Field(min_length=1, max_length=255)
    control_state: Literal["BOT_ACTIVE", "HUMAN_ACTIVE", "HUMAN_REQUESTED", "BOT_RESUMING", "CLOSED"] = "BOT_ACTIVE"
    automated: bool = True
    correlation_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def at_least_one_payload(self) -> "OutboundMessage":
        if self.content is None and self.media is None:
            raise ValueError("mensagem sem conteúdo ou mídia")
        return self


class GatewayReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_message_id: str = Field(min_length=1, max_length=255)
    status: str = Field(min_length=1, max_length=32)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReplayStore(Protocol):
    async def seen_or_mark(self, key: str, ttl_seconds: int) -> bool: ...


class EventStore(Protocol):
    async def persist_before_process(self, event: InboundEvent, raw_body: bytes) -> bool: ...


class OutboxStore(Protocol):
    async def mark_delivered(self, idempotency_key: str, receipt: GatewayReceipt) -> None: ...

    async def is_recipient_opted_out(self, tenant_id: UUID, contact_id: UUID) -> bool: ...


class OutboxRouteResolver(Protocol):
    async def prepare_outbox(self, message: OutboundMessage) -> Any: ...

    async def resolve_for_send(self, message: OutboundMessage) -> Any: ...

    async def send(self, message: OutboundMessage) -> GatewayReceipt: ...


class WhatsAppAdapter(ABC):
    @abstractmethod
    async def health(self) -> dict[str, Any]: ...

    @abstractmethod
    async def session(self) -> SessionSnapshot: ...

    @abstractmethod
    async def send(self, message: OutboundMessage) -> GatewayReceipt: ...


class OpenWAWhatsAppAdapter(WhatsAppAdapter):
    def __init__(self, *, base_url: str, api_key: str, session_id: str, tenant_id: UUID, owner_ref: str, webhook_secret: str, client: httpx.AsyncClient | None = None, replay_store: ReplayStore | None = None, shard_id: str | None = None):
        if not api_key or not webhook_secret:
            raise ValueError("credenciais do OpenWA ausentes")
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.session_id = session_id
        self.tenant_id = tenant_id
        self.owner_ref = owner_ref
        self._webhook_secret = webhook_secret.encode()
        self.client = client
        self.replay_store = replay_store
        self.shard_id = shard_id

    async def health(self) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            response = await self._request("GET", "/api/health/live", retry=True)
        except Exception:
            record_integration("openwa", "error", (time.perf_counter() - started) * 1000)
            raise
        record_integration("openwa", "success", (time.perf_counter() - started) * 1000)
        return {"status": "healthy" if response.status_code < 400 else "unhealthy", "version": OPENWA_VERSION, "session_id": self.session_id}

    async def session(self) -> SessionSnapshot:
        started = time.perf_counter()
        try:
            response = await self._request(
                "GET", f"/api/sessions/{self.session_id}", retry=True
            )
        except Exception:
            record_integration("whatsapp_session", "error", (time.perf_counter() - started) * 1000)
            raise
        response.raise_for_status()
        state = response.json()
        status = self._map_session_status(state)
        # Ownership is a KS concern and is fenced by ChannelRouter. OpenWA's
        # session DTO does not expose an owner, so do not infer one from an
        # undocumented gateway field.
        snapshot = SessionSnapshot(
            tenant_id=self.tenant_id,
            session_id=self.session_id,
            owner_ref=self.owner_ref,
            status=status,
            version=OPENWA_VERSION,
            secure=status == SessionStatus.CONNECTED and bool(state.get("engineLoaded")),
        )
        latency = (time.perf_counter() - started) * 1000
        record_integration("whatsapp_session", "success", latency)
        metrics.set_gauge(
            "ks_openwa_session_info",
            1 if snapshot.secure else 0,
            labels={
                "version": OPENWA_VERSION,
                "connection": snapshot.status.value,
                "owner_state": "owned" if snapshot.owner_ref == self.owner_ref else "conflict",
                "shard_state": "assigned" if self.shard_id else "unassigned",
            },
        )
        return snapshot

    async def verify_and_persist_webhook(self, raw_body: bytes, signature: str, timestamp: str | None = None, nonce: str | None = None, event_store: EventStore | None = None, now: float | None = None) -> tuple[InboundEvent, bool]:
        if event_store is None:
            raise ValueError("event_store obrigatorio")
        if timestamp is None and nonce is None:
            return await self._verify_official_webhook(raw_body, signature, event_store)
        if timestamp is None or nonce is None:
            raise ReplayError("timestamp e nonce devem ser enviados juntos")
        if len(raw_body) > MAX_WEBHOOK_PAYLOAD_BYTES:
            raise GatewayError("payload de webhook excede o limite")
        current = time.time() if now is None else now
        try:
            stamp = int(timestamp)
        except ValueError as exc:
            raise ReplayError("timestamp inválido") from exc
        if abs(current - stamp) > MAX_WEBHOOK_AGE_SECONDS:
            raise ReplayError("webhook expirado")
        if len(nonce) > MAX_WEBHOOK_NONCE_LENGTH or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", nonce):
            raise ReplayError("nonce inválido")
        # The body remains byte-for-byte intact for persistence. Binding the
        # signed metadata prevents an attacker from replacing a fresh header
        # around an otherwise valid body and bypassing the replay window.
        signed_bytes = timestamp.encode("ascii") + b"." + nonce.encode("ascii") + b"." + raw_body
        expected = "sha256=" + hmac.new(self._webhook_secret, signed_bytes, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise GatewayError("assinatura inválida")
        raw_event = json.loads(raw_body)
        raw_event["tenant_id"] = str(self.tenant_id)
        raw_event["session_id"] = self.session_id
        payload = InboundEvent.model_validate(raw_event)
        if payload.correlation_id is None:
            payload = payload.model_copy(update={"correlation_id": str(uuid4())})
        replay_key = f"openwa:webhook:{self.session_id}:{nonce}"
        if self.replay_store and await self.replay_store.seen_or_mark(replay_key, MAX_WEBHOOK_AGE_SECONDS):
            metrics.inc("ks_duplicates_total", labels={"kind": "webhook", "provider": "openwa"})
            raise ReplayError("webhook repetido")
        persisted = await event_store.persist_before_process(payload, raw_body)
        metrics.set_gauge(
            "ks_openwa_session_last_webhook_timestamp",
            current,
            labels={"session_id": hashlib.sha256(self.session_id.encode()).hexdigest()[:12]},
        )
        logger.info("openwa_webhook_persisted", extra={"correlation_id": payload.correlation_id})
        return payload, not persisted

    async def _verify_official_webhook(
        self, raw_body: bytes, signature: str, event_store: EventStore
    ) -> tuple[InboundEvent, bool]:
        """Verify OpenWA v0.23.3's documented body-only signature.

        OpenWA does not emit timestamp/nonce headers. The internal KS ingress
        variant above adds those fields and signs them; this path still gets
        durable event-id deduplication before processing.
        """
        if len(raw_body) > MAX_WEBHOOK_PAYLOAD_BYTES:
            raise GatewayError("payload de webhook excede o limite")
        expected = "sha256=" + hmac.new(
            self._webhook_secret, raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise GatewayError("assinatura invalida")
        try:
            raw_event = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GatewayError("payload de webhook invalido") from exc
        payload = self._normalize_inbound_event(raw_event)
        persisted = await event_store.persist_before_process(payload, raw_body)
        logger.info("openwa_webhook_persisted", extra={"correlation_id": payload.correlation_id})
        return payload, not persisted

    def _normalize_inbound_event(self, raw_event: dict[str, Any]) -> InboundEvent:
        data_value = raw_event.get("data")
        data: dict[str, Any] = data_value if isinstance(data_value, dict) else raw_event
        message_value = data.get("message")
        message: dict[str, Any] = message_value if isinstance(message_value, dict) else data
        event_id = (
            raw_event.get("event_id")
            or raw_event.get("eventId")
            or data.get("event_id")
            or data.get("id")
            or data.get("messageId")
        )
        sender = (
            raw_event.get("sender_ref")
            or data.get("sender_ref")
            or data.get("from")
            or data.get("author")
            or data.get("participant")
        )
        content = raw_event.get("content")
        if content is None:
            content = data.get("body") or data.get("text") or message.get("body")
        if not isinstance(event_id, str) or not event_id:
            raise GatewayError("webhook sem identificador de evento")
        if not isinstance(sender, str) or not sender:
            raise GatewayError("webhook sem remetente")
        event_type = str(
            raw_event.get("event_type")
            or raw_event.get("event")
            or raw_event.get("type")
            or "message"
        )
        return InboundEvent.model_validate(
            {
                "event_id": event_id,
                "tenant_id": self.tenant_id,
                "session_id": self.session_id,
                "event_type": event_type,
                "external_message_id": data.get("messageId") or data.get("id"),
                "sender_ref": sender,
                "content": content,
                "occurred_at": raw_event.get("occurred_at") or data.get("timestamp") or datetime.now(timezone.utc),
            }
        )

    @staticmethod
    def _map_session_status(state: dict[str, Any]) -> SessionStatus:
        value = str(state.get("status") or state.get("state") or "").lower()
        if value in {"ready", "connected", "online"}:
            return SessionStatus.CONNECTED
        if value in {"qr_ready", "qr", "qr_required"}:
            return SessionStatus.QR_REQUIRED
        if value in {"action_required", "relink_required"}:
            return SessionStatus.RELINK_REQUIRED
        if value in {"failed", "error"}:
            return SessionStatus.ERROR
        return SessionStatus.DISCONNECTED

    def _send_request(self, message: OutboundMessage) -> tuple[str, dict[str, Any]]:
        if message.content is not None and len(message.content.encode("utf-8")) > MAX_OPENWA_TEXT_BYTES:
            raise GatewayError("texto excede o limite de 4096 bytes do OpenWA")
        if message.content is not None and message.media is None:
            return f"/api/sessions/{self.session_id}/messages/send-text", {
                "chatId": message.recipient_ref,
                "text": message.content,
            }
        assert message.media is not None
        source = message.media.storage_ref
        if not source.startswith(("http://", "https://")):
            raise GatewayError("midia precisa ser URL HTTP(S) pre-assinada para o OpenWA")
        payload: dict[str, Any] = {
            "chatId": message.recipient_ref,
            "url": source,
            "mimetype": message.media.mime_type,
        }
        if message.content is not None:
            payload["caption"] = message.content
        path_kind = {
            MediaKind.IMAGE: "image",
            MediaKind.AUDIO: "audio",
            MediaKind.DOCUMENT: "document",
        }[message.media.kind]
        return f"/api/sessions/{self.session_id}/messages/send-{path_kind}", payload

    async def send(self, message: OutboundMessage) -> GatewayReceipt:
        started = time.perf_counter()
        if message.tenant_id != self.tenant_id or message.session_id != self.session_id:
            raise UnsafeSessionError("tenant ou sessão divergente")
        snapshot = await self.session()
        if snapshot.owner_ref != self.owner_ref or snapshot.status != SessionStatus.CONNECTED or not snapshot.secure:
            raise UnsafeSessionError("sessão OpenWA insegura ou desconectada")
        if message.automated and message.control_state == "HUMAN_ACTIVE":
            raise UnsafeSessionError("controle humano ativo; envio automático bloqueado")
        path, payload = self._send_request(message)
        try:
            # OpenWA v0.23.3 has no idempotency-key contract. Retrying a POST
            # after a timeout could duplicate a WhatsApp message.
            response = await self._request("POST", path, json=payload, retry=False)
        except Exception:
            record_integration("openwa", "error", (time.perf_counter() - started) * 1000)
            raise
        response.raise_for_status()
        record_integration("openwa", "success", (time.perf_counter() - started) * 1000)
        data = response.json()
        external_id = data.get("messageId")
        if not isinstance(external_id, str) or not external_id:
            raise GatewayError("receipt OpenWA sem messageId")
        occurred_at = datetime.now(timezone.utc)
        if isinstance(data.get("timestamp"), (int, float)):
            occurred_at = datetime.fromtimestamp(float(data["timestamp"]), tz=timezone.utc)
        metrics.set_gauge(
            "ks_openwa_session_last_receipt_timestamp",
            time.time(),
            labels={"session_id": hashlib.sha256(self.session_id.encode()).hexdigest()[:12]},
        )
        logger.info("openwa_send_confirmed", extra={"correlation_id": message.correlation_id})
        return GatewayReceipt(
            external_message_id=external_id, status="SENT", occurred_at=occurred_at
        )

    async def _request(self, method: str, path: str, *, json: dict[str, Any] | None = None, retry: bool = False) -> httpx.Response:
        client = self.client or httpx.AsyncClient(timeout=10)
        close = self.client is None
        try:
            for attempt in range(3 if retry else 1):
                try:
                    response = await client.request(
                        method,
                        self.base_url + path,
                        headers={"X-API-Key": self._api_key},
                        json=json,
                    )
                    if retry and (response.status_code in {408, 429} or response.status_code >= 500) and attempt < 2:
                        await asyncio.sleep(0.05 * (2**attempt))
                        continue
                    return response
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if not retry or attempt >= 2:
                        raise GatewayError("OpenWA indisponível") from exc
                    await asyncio.sleep(0.05 * (2**attempt))
            raise GatewayError("OpenWA indisponível")
        finally:
            if close:
                await client.aclose()


class FakeWhatsAppGateway(WhatsAppAdapter):
    def __init__(self, snapshot: SessionSnapshot):
        self.snapshot = snapshot
        self.sent: dict[str, GatewayReceipt] = {}
        self.received: list[InboundEvent] = []

    async def health(self) -> dict[str, Any]:
        return {"status": "healthy", "version": self.snapshot.version, "session_id": self.snapshot.session_id}

    async def session(self) -> SessionSnapshot:
        return self.snapshot

    async def send(self, message: OutboundMessage) -> GatewayReceipt:
        if message.tenant_id != self.snapshot.tenant_id or message.session_id != self.snapshot.session_id:
            raise UnsafeSessionError("tenant ou sessão divergente")
        if self.snapshot.status != SessionStatus.CONNECTED or not self.snapshot.secure:
            raise UnsafeSessionError("sessão insegura")
        if message.automated and message.control_state == "HUMAN_ACTIVE":
            raise UnsafeSessionError("controle humano ativo")
        if message.idempotency_key in self.sent:
            metrics.inc("ks_duplicates_total", labels={"kind": "outbound", "provider": "fake"})
            return self.sent[message.idempotency_key]
        receipt = GatewayReceipt(external_message_id=str(uuid4()), status="SENT")
        self.sent[message.idempotency_key] = receipt
        return receipt


class SqlAlchemyEventStore:
    """Persiste o evento normalizado antes de qualquer processamento de domínio."""

    def __init__(self, session: Any):
        self.session = session

    async def persist_before_process(self, event: InboundEvent, raw_body: bytes) -> bool:
        from sqlalchemy import select
        from ..db.models import ChannelSession, WebhookEvent

        existing = await self.session.scalar(select(WebhookEvent).where(WebhookEvent.tenant_id == event.tenant_id, WebhookEvent.provider_event_id == event.event_id))
        if existing:
            return False
        self.session.add(WebhookEvent(id=uuid4(), tenant_id=event.tenant_id, provider="OPENWA", provider_event_id=event.event_id, event_type=event.event_type, payload=json.loads(raw_body)))
        channel_session = await self.session.scalar(
            select(ChannelSession).where(
                ChannelSession.tenant_id == event.tenant_id,
                ChannelSession.external_session_id == event.session_id,
            )
        )
        if channel_session is not None:
            channel_session.last_webhook_at = event.occurred_at
        await self.session.commit()
        return True


class OutboxDispatcher:
    """Transporta apenas entradas já materializadas no outbox."""

    def __init__(self, adapter: WhatsAppAdapter, store: OutboxStore, automatic_sender: Any | None = None, router: OutboxRouteResolver | None = None, opt_out_checker: Callable[[UUID, UUID], Awaitable[bool]] | None = None):
        self.adapter = adapter
        self.store = store
        self.automatic_sender = automatic_sender
        self.router = router
        self.opt_out_checker = opt_out_checker or getattr(store, "is_recipient_opted_out", None)

    async def dispatch(self, message: OutboundMessage) -> GatewayReceipt:
        if (
            message.automated
            and message.recipient_contact_id is not None
            and self.opt_out_checker is not None
            and await self.opt_out_checker(message.tenant_id, message.recipient_contact_id)
        ):
            metrics.inc("ks_blocked_sends_total", labels={"reason": "opt_out"})
            raise UnsafeSessionError("contato em opt-out")
        if self.router:
            await self.router.resolve_for_send(message)
            # The router is the final transport boundary. An optional
            # automatic sender must not bypass its second ownership/fencing
            # read after the outbox row has been selected.
            receipt = await self.router.send(message)
        elif message.automated:
            sender = self.automatic_sender or self.router
            if sender is None:
                raise UnsafeSessionError("envio automático sem gate de controle configurado")
            receipt = await sender.send(message)
        elif self.router:
            receipt = await self.router.send(message)
        else:
            receipt = await self.adapter.send(message)
        await self.store.mark_delivered(message.idempotency_key, receipt)
        return receipt


class SqlAlchemyOutboxStore:
    """Transactional outbox store; the dispatcher is the only transport caller."""

    def __init__(self, session: Any, router: OutboxRouteResolver | None = None):
        self.session = session
        self.router = router

    async def is_recipient_opted_out(self, tenant_id: UUID, contact_id: UUID) -> bool:
        from sqlalchemy import select
        from ..db.models import Contact

        contact = await self.session.scalar(
            select(Contact).where(Contact.tenant_id == tenant_id, Contact.id == contact_id)
        )
        return bool(contact and contact.opted_out_at is not None)

    async def enqueue(self, message: OutboundMessage) -> str:
        from sqlalchemy import select
        from ..db.models import OutboxEvent

        route = await self.router.prepare_outbox(message) if self.router else None
        existing = await self.session.scalar(select(OutboxEvent).where(OutboxEvent.tenant_id == message.tenant_id, OutboxEvent.idempotency_key == message.idempotency_key))
        if existing:
            metrics.inc("ks_duplicates_total", labels={"kind": "outbox", "provider": "whatsapp"})
            return str(existing.id)
        event_id = uuid4()
        payload = message.model_dump(mode="json")
        if route is not None:
            payload["routing"] = {
                "gateway_id": str(route.gateway_id),
                "external_session_id": route.external_session_id,
                "owner_epoch": route.owner_epoch,
            }
        self.session.add(OutboxEvent(id=event_id, tenant_id=message.tenant_id, aggregate_type="conversation", aggregate_id=message.conversation_id, event_type="WHATSAPP_SEND", idempotency_key=message.idempotency_key, payload=payload))
        await self.session.commit()
        return str(event_id)

    async def mark_delivered(self, idempotency_key: str, receipt: GatewayReceipt) -> None:
        from datetime import datetime, timezone
        from sqlalchemy import select
        from ..db.models import ChannelSession, OutboxEvent

        event = await self.session.scalar(select(OutboxEvent).where(OutboxEvent.idempotency_key == idempotency_key))
        if event:
            event.status = "DELIVERED"
            event.delivered_at = datetime.now(timezone.utc)
            event.payload = {**event.payload, "receipt_id": receipt.external_message_id, "receipt_status": receipt.status}
            session_id = event.payload.get("session_id")
            if isinstance(session_id, str):
                channel_session = await self.session.scalar(
                    select(ChannelSession).where(
                        ChannelSession.tenant_id == event.tenant_id,
                        ChannelSession.external_session_id == session_id,
                    )
                )
                if channel_session is not None:
                    channel_session.last_receipt_at = datetime.now(timezone.utc)
            await self.session.commit()
