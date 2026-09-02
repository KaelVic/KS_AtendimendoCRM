from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import AuditEvent, Conversation, ConversationControl, Message
from ..integrations.whatsapp import GatewayReceipt, OutboundMessage, WhatsAppAdapter

logger = logging.getLogger("ks_control")
CONTROL_POLICY_VERSION = "control-v1"


class ControlState(StrEnum):
    BOT_ACTIVE = "BOT_ACTIVE"
    HUMAN_REQUESTED = "HUMAN_REQUESTED"
    HUMAN_ACTIVE = "HUMAN_ACTIVE"
    AI_ASSISTED_PENDING = "AI_ASSISTED_PENDING"
    BOT_RESUMING = "BOT_RESUMING"
    CLOSED = "CLOSED"


class ControlAction(StrEnum):
    ASSUME = "ASSUME"
    RETURN = "RETURN"
    REQUEST_ASSIST = "REQUEST_ASSIST"
    COMPLETE_ASSIST = "COMPLETE_ASSIST"
    RESUME = "RESUME"


class ControlStateError(RuntimeError):
    pass


class StaleControlVersion(ControlStateError):
    pass


class ControlBusy(ControlStateError):
    pass


class AutomaticSendBlocked(ControlStateError):
    pass


def transition_state(current: ControlState, action: ControlAction) -> ControlState:
    allowed: dict[ControlAction, dict[ControlState, ControlState]] = {
        ControlAction.ASSUME: {
            ControlState.BOT_ACTIVE: ControlState.HUMAN_ACTIVE,
            ControlState.HUMAN_REQUESTED: ControlState.HUMAN_ACTIVE,
            ControlState.AI_ASSISTED_PENDING: ControlState.HUMAN_ACTIVE,
            ControlState.BOT_RESUMING: ControlState.HUMAN_ACTIVE,
        },
        ControlAction.RETURN: {ControlState.HUMAN_ACTIVE: ControlState.BOT_RESUMING},
        ControlAction.REQUEST_ASSIST: {
            ControlState.BOT_ACTIVE: ControlState.AI_ASSISTED_PENDING,
            ControlState.HUMAN_REQUESTED: ControlState.AI_ASSISTED_PENDING,
        },
        ControlAction.COMPLETE_ASSIST: {
            ControlState.AI_ASSISTED_PENDING: ControlState.HUMAN_ACTIVE,
        },
        ControlAction.RESUME: {ControlState.BOT_RESUMING: ControlState.BOT_ACTIVE},
    }
    try:
        return allowed[action][current]
    except KeyError as exc:
        raise ControlStateError(f"transição inválida: {current}->{action}") from exc


@dataclass(frozen=True)
class ControlSnapshot:
    tenant_id: UUID
    conversation_id: UUID
    state: ControlState
    version: int


@dataclass(frozen=True)
class ControlEvent:
    event_id: UUID
    tenant_id: UUID
    conversation_id: UUID
    previous_state: ControlState
    state: ControlState
    version: int
    actor_user_id: UUID | None
    reason: str
    policy_version: str
    occurred_at: datetime

    def payload(self) -> dict[str, str | int | None]:
        return {
            "event_id": str(self.event_id),
            "event_type": "CONVERSATION_CONTROL_CHANGED",
            "tenant_id": str(self.tenant_id),
            "conversation_id": str(self.conversation_id),
            "previous_state": self.previous_state.value,
            "state": self.state.value,
            "version": self.version,
            "actor_user_id": str(self.actor_user_id) if self.actor_user_id else None,
            "reason": self.reason,
            "policy_version": self.policy_version,
            "occurred_at": self.occurred_at.isoformat(),
        }


class ControlEventPublisher(Protocol):
    async def publish(self, event: ControlEvent) -> None: ...


class InMemoryControlEventPublisher:
    def __init__(self):
        self.events: list[ControlEvent] = []

    async def publish(self, event: ControlEvent) -> None:
        self.events.append(event)


class RedisControlEventPublisher:
    def __init__(self, redis: Any, channel_prefix: str = "ks:control"):
        self.redis = redis
        self.channel_prefix = channel_prefix

    async def publish(self, event: ControlEvent) -> None:
        channel = f"{self.channel_prefix}:{event.tenant_id}:{event.conversation_id}"
        await self.redis.publish(channel, json.dumps(event.payload(), ensure_ascii=False))


class InMemoryConversationGate:
    def __init__(self):
        self._locks: dict[tuple[UUID, UUID], asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    @asynccontextmanager
    async def hold(self, tenant_id: UUID, conversation_id: UUID):
        key = (tenant_id, conversation_id)
        async with self._guard:
            lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            yield


class RedisConversationGate:
    def __init__(self, redis: Any, ttl_seconds: int = 60):
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    @asynccontextmanager
    async def hold(self, tenant_id: UUID, conversation_id: UUID):
        lock = self.redis.lock(
            f"ks:control-gate:{tenant_id}:{conversation_id}",
            timeout=self.ttl_seconds,
            blocking_timeout=self.ttl_seconds,
        )
        acquired = await lock.acquire()
        if not acquired:
            raise ControlBusy("controle ocupado; tente novamente")
        try:
            yield
        finally:
            await lock.release()


class HumanIntervalSummarizer(Protocol):
    async def summarize(self, messages: list["MessageSnapshot"]) -> "HumanIntervalSummary": ...


@dataclass(frozen=True)
class MessageSnapshot:
    direction: str
    message_type: str
    content: str | None
    created_at: datetime


@dataclass(frozen=True)
class HumanIntervalSummary:
    summary: str
    commercial_state: str


class DeterministicHumanIntervalSummarizer:
    async def summarize(self, messages: list[MessageSnapshot]) -> HumanIntervalSummary:
        lines = [
            f"{message.direction}: {(message.content or '[' + message.message_type + ']')[:1000]}"
            for message in messages
        ]
        return HumanIntervalSummary(
            summary="Intervalo humano desde a última assunção:\n" + "\n".join(lines),
            commercial_state="PENDING_REVIEW" if messages else "UNKNOWN",
        )


@dataclass(frozen=True)
class AssistedDraft:
    content: str
    facts_hash: str
    policy_version: str


class AssistedResponseFormatter(Protocol):
    async def format(self, facts: str, tone: str) -> AssistedDraft: ...


class DeterministicAssistedFormatter:
    async def format(self, facts: str, tone: str) -> AssistedDraft:
        del tone
        return AssistedDraft(
            content=facts,
            facts_hash=hashlib.sha256(facts.encode("utf-8")).hexdigest(),
            policy_version=CONTROL_POLICY_VERSION,
        )


class InMemoryControlStore:
    """CAS store used by tests and local fakes; production uses SQL UPDATE ... version."""

    def __init__(self, snapshot: ControlSnapshot):
        self.snapshot = snapshot
        self._lock = asyncio.Lock()

    async def read(self, tenant_id: UUID, conversation_id: UUID) -> ControlSnapshot:
        if (tenant_id, conversation_id) != (self.snapshot.tenant_id, self.snapshot.conversation_id):
            raise ControlStateError("controle fora do tenant")
        return self.snapshot

    async def cas(self, expected_version: int, action: ControlAction) -> ControlSnapshot:
        async with self._lock:
            if self.snapshot.version != expected_version:
                raise StaleControlVersion("versão de controle desatualizada")
            next_state = transition_state(self.snapshot.state, action)
            self.snapshot = ControlSnapshot(
                tenant_id=self.snapshot.tenant_id,
                conversation_id=self.snapshot.conversation_id,
                state=next_state,
                version=self.snapshot.version + 1,
            )
            return self.snapshot


class ControlService:
    def __init__(
        self,
        session: AsyncSession,
        publisher: ControlEventPublisher,
        gate: Any | None = None,
        policy_version: str = CONTROL_POLICY_VERSION,
    ):
        self.session = session
        self.publisher = publisher
        self.gate = gate
        self.policy_version = policy_version

    async def transition(
        self,
        *,
        tenant_id: UUID,
        conversation_id: UUID,
        action: ControlAction,
        expected_version: int | None,
        actor_user_id: UUID | None,
        reason: str,
        correlation_id: str | None = None,
    ) -> ControlEvent:
        async with self._held(tenant_id, conversation_id):
            return await self._transition(
                tenant_id=tenant_id, conversation_id=conversation_id, action=action,
                expected_version=expected_version, actor_user_id=actor_user_id, reason=reason,
                correlation_id=correlation_id,
            )

    async def _transition(
        self, *, tenant_id: UUID, conversation_id: UUID, action: ControlAction,
        expected_version: int | None, actor_user_id: UUID | None, reason: str,
        correlation_id: str | None = None,
    ) -> ControlEvent:
        current = await self.session.scalar(
            select(ConversationControl).where(
                ConversationControl.tenant_id == tenant_id,
                ConversationControl.conversation_id == conversation_id,
            )
        )
        if current is None:
            raise LookupError("CONVERSATION_NOT_FOUND")
        expected = current.version if expected_version is None else expected_version
        if current.version != expected:
            raise StaleControlVersion("versão de controle desatualizada")
        previous = ControlState(current.state)
        next_state = transition_state(previous, action)
        now = datetime.now(timezone.utc)
        values: dict[str, Any] = {
            "state": next_state.value,
            "version": ConversationControl.version + 1,
            "changed_by_user_id": actor_user_id,
            "updated_at": now,
        }
        if next_state == ControlState.HUMAN_ACTIVE:
            values["human_started_at"] = now
        if next_state == ControlState.BOT_RESUMING:
            values["human_started_at"] = current.human_started_at or now
        changed = await self.session.execute(
            update(ConversationControl)
            .where(
                ConversationControl.tenant_id == tenant_id,
                ConversationControl.conversation_id == conversation_id,
                ConversationControl.version == expected,
                ConversationControl.state == previous.value,
            )
            .values(**values)
        )
        if getattr(changed, "rowcount", 0) != 1:
            await self.session.rollback()
            raise StaleControlVersion("controle alterado por outro operador")
        self.session.add(
            AuditEvent(
                id=uuid4(), tenant_id=tenant_id, actor_user_id=actor_user_id,
                action=f"CONVERSATION_CONTROL_{action.value}", target_type="conversation",
                target_id=conversation_id, correlation_id=correlation_id or str(uuid4()),
                event_metadata={
                    "previous_state": previous.value, "state": next_state.value,
                    "version": expected + 1, "reason": reason[:500],
                    "policy_version": self.policy_version,
                }, created_at=now, updated_at=now,
            )
        )
        await self.session.commit()
        event = ControlEvent(
            event_id=uuid4(), tenant_id=tenant_id, conversation_id=conversation_id,
            previous_state=previous, state=next_state, version=expected + 1,
            actor_user_id=actor_user_id, reason=reason[:500],
            policy_version=self.policy_version, occurred_at=now,
        )
        try:
            await self.publisher.publish(event)
        except Exception as exc:  # persisted state remains authoritative
            logger.warning("falha ao publicar evento de controle; estado já persistido: %s", type(exc).__name__)
        return event

    async def return_to_bot(
        self, *, tenant_id: UUID, conversation_id: UUID, expected_version: int | None,
        actor_user_id: UUID | None, reason: str,
        summarizer: HumanIntervalSummarizer | None = None,
        correlation_id: str | None = None,
    ) -> ControlEvent:
        async with self._held(tenant_id, conversation_id):
            resumed = await self._transition(
                tenant_id=tenant_id, conversation_id=conversation_id, action=ControlAction.RETURN,
                expected_version=expected_version, actor_user_id=actor_user_id, reason=reason,
                correlation_id=correlation_id,
            )
            control = await self.session.scalar(
                select(ConversationControl).where(
                    ConversationControl.tenant_id == tenant_id,
                    ConversationControl.conversation_id == conversation_id,
                )
            )
            conversation = await self.session.scalar(
                select(Conversation).where(
                    Conversation.tenant_id == tenant_id, Conversation.id == conversation_id,
                )
            )
            if control is None or conversation is None or control.human_started_at is None:
                raise ControlStateError("intervalo humano ausente")
            rows = list(await self.session.scalars(
                select(Message).where(
                    Message.tenant_id == tenant_id,
                    Message.conversation_id == conversation_id,
                    Message.created_at >= control.human_started_at,
                ).order_by(Message.created_at, Message.id)
            ))
            interval = [
                MessageSnapshot(row.direction, row.message_type, row.content, row.created_at)
                for row in rows
            ]
            summary = await (summarizer or DeterministicHumanIntervalSummarizer()).summarize(interval)
            if not summary.summary or summary.commercial_state not in {"UNKNOWN", "PENDING_REVIEW"}:
                raise ControlStateError("resumo de intervalo inválido")
            now = datetime.now(timezone.utc)
            changed = await self.session.execute(
                update(ConversationControl)
                .where(
                    ConversationControl.tenant_id == tenant_id,
                    ConversationControl.conversation_id == conversation_id,
                    ConversationControl.state == ControlState.BOT_RESUMING.value,
                    ConversationControl.version == resumed.version,
                )
                .values(
                    state=ControlState.BOT_ACTIVE.value,
                    version=ConversationControl.version + 1,
                    last_human_summary_at=now,
                    human_started_at=None,
                    updated_at=now,
                )
            )
            if getattr(changed, "rowcount", 0) != 1:
                await self.session.rollback()
                raise StaleControlVersion("controle alterado durante a retomada")
            conversation.context_summary = summary.summary[:12_000]
            conversation.commercial_state = summary.commercial_state
            conversation.updated_at = now
            self.session.add(
                AuditEvent(
                    id=uuid4(), tenant_id=tenant_id, actor_user_id=actor_user_id,
                    action="CONVERSATION_CONTROL_RESUMED", target_type="conversation",
                    target_id=conversation_id, correlation_id=correlation_id or str(uuid4()),
                    event_metadata={
                        "previous_state": ControlState.BOT_RESUMING.value,
                        "state": ControlState.BOT_ACTIVE.value,
                        "version": resumed.version + 1,
                        "human_message_count": len(interval),
                        "reason": reason[:500], "policy_version": self.policy_version,
                    }, created_at=now, updated_at=now,
                )
            )
            await self.session.commit()
            event = ControlEvent(
                event_id=uuid4(), tenant_id=tenant_id, conversation_id=conversation_id,
                previous_state=ControlState.BOT_RESUMING, state=ControlState.BOT_ACTIVE,
                version=resumed.version + 1, actor_user_id=actor_user_id,
                reason=reason[:500], policy_version=self.policy_version, occurred_at=now,
            )
            try:
                await self.publisher.publish(event)
            except Exception as exc:
                logger.warning("falha ao publicar retomada de controle: %s", type(exc).__name__)
            return event

    async def resolve_assisted(
        self, *, tenant_id: UUID, conversation_id: UUID, expected_version: int,
        actor_user_id: UUID | None, human_content: str | None, approved_draft: AssistedDraft | None,
        tone: str = "natural", formatter: AssistedResponseFormatter | None = None,
        correlation_id: str | None = None,
    ) -> AssistedDraft:
        if human_content and approved_draft:
            raise ControlStateError("forneça conteúdo ou aprovação, não ambos")
        if not human_content and not approved_draft:
            raise ControlStateError("conteúdo ou aprovação humana obrigatória")
        if approved_draft:
            if approved_draft.policy_version != self.policy_version:
                raise ControlStateError("versão de política do rascunho incompatível")
            if hashlib.sha256(approved_draft.content.encode("utf-8")).hexdigest() != approved_draft.facts_hash:
                raise ControlStateError("rascunho alterado após aprovação")
            draft = approved_draft
        else:
            draft = await (formatter or DeterministicAssistedFormatter()).format(human_content or "", tone)
            expected_hash = hashlib.sha256((human_content or "").encode("utf-8")).hexdigest()
            if draft.facts_hash != expected_hash or draft.policy_version != self.policy_version:
                raise ControlStateError("formatter alterou fatos ou política")
        await self.transition(
            tenant_id=tenant_id, conversation_id=conversation_id, action=ControlAction.COMPLETE_ASSIST,
            expected_version=expected_version, actor_user_id=actor_user_id,
            reason="resposta assistida aprovada/fornecida", correlation_id=correlation_id,
        )
        return draft

    @asynccontextmanager
    async def _held(self, tenant_id: UUID, conversation_id: UUID):
        if self.gate is None:
            yield
        else:
            async with self.gate.hold(tenant_id, conversation_id):
                yield


class ControlReader(Protocol):
    async def read(self, tenant_id: UUID, conversation_id: UUID) -> ControlSnapshot: ...


class SqlAlchemyControlReader:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def read(self, tenant_id: UUID, conversation_id: UUID) -> ControlSnapshot:
        control = await self.session.scalar(
            select(ConversationControl).where(
                ConversationControl.tenant_id == tenant_id,
                ConversationControl.conversation_id == conversation_id,
            )
        )
        if control is None:
            raise ControlStateError("CONVERSATION_NOT_FOUND")
        return ControlSnapshot(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            state=ControlState(control.state),
            version=control.version,
        )


class SafeAutomaticSender:
    """Re-reads persisted control while holding the same conversation gate as handoff."""

    def __init__(self, adapter: WhatsAppAdapter, reader: ControlReader, gate: Any):
        self.adapter = adapter
        self.reader = reader
        self.gate = gate

    async def send(self, message: OutboundMessage) -> GatewayReceipt:
        if not message.automated:
            return await self.adapter.send(message)
        async with self.gate.hold(message.tenant_id, message.conversation_id):
            first = await self.reader.read(message.tenant_id, message.conversation_id)
            if first.state != ControlState.BOT_ACTIVE:
                raise AutomaticSendBlocked("envio automático bloqueado pelo controle atual")
            # The second read is deliberately adjacent to the gateway call.
            latest = await self.reader.read(message.tenant_id, message.conversation_id)
            if latest.state != ControlState.BOT_ACTIVE:
                raise AutomaticSendBlocked("controle humano assumiu antes do envio")
            return await self.adapter.send(message.model_copy(update={"control_state": latest.state.value}))
