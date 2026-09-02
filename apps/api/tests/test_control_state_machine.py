from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.control import (
    AutomaticSendBlocked,
    ControlAction,
    ControlState,
    DeterministicAssistedFormatter,
    InMemoryControlStore,
    InMemoryConversationGate,
    SafeAutomaticSender,
    StaleControlVersion,
    transition_state,
)
from src.control.state_machine import ControlSnapshot
from src.integrations.whatsapp import (
    FakeWhatsAppGateway,
    OutboxDispatcher,
    OutboundMessage,
    SessionSnapshot,
    SessionStatus,
    UnsafeSessionError,
)


TENANT = uuid4()
CONVERSATION = uuid4()


def snapshot(state=ControlState.BOT_ACTIVE, version=1):
    return ControlSnapshot(TENANT, CONVERSATION, state, version)


def outbound():
    return OutboundMessage(
        tenant_id=TENANT,
        conversation_id=CONVERSATION,
        session_id="pilot",
        recipient_ref="opaque-recipient",
        content="resposta aprovada",
        idempotency_key="outbox-1",
    )


@pytest.mark.parametrize(
    ("state", "action", "expected"),
    [
        (ControlState.BOT_ACTIVE, ControlAction.ASSUME, ControlState.HUMAN_ACTIVE),
        (ControlState.HUMAN_REQUESTED, ControlAction.ASSUME, ControlState.HUMAN_ACTIVE),
        (ControlState.HUMAN_ACTIVE, ControlAction.RETURN, ControlState.BOT_RESUMING),
        (ControlState.BOT_RESUMING, ControlAction.RESUME, ControlState.BOT_ACTIVE),
        (ControlState.BOT_ACTIVE, ControlAction.REQUEST_ASSIST, ControlState.AI_ASSISTED_PENDING),
        (ControlState.AI_ASSISTED_PENDING, ControlAction.COMPLETE_ASSIST, ControlState.HUMAN_ACTIVE),
    ],
)
def test_control_transitions_are_explicit(state, action, expected):
    assert transition_state(state, action) == expected


@pytest.mark.asyncio
async def test_optimistic_control_allows_only_one_concurrent_assumption():
    store = InMemoryControlStore(snapshot())
    results = await asyncio.gather(
        store.cas(1, ControlAction.ASSUME),
        store.cas(1, ControlAction.ASSUME),
        return_exceptions=True,
    )
    assert sum(isinstance(result, ControlSnapshot) for result in results) == 1
    assert sum(isinstance(result, StaleControlVersion) for result in results) == 1
    assert store.snapshot.state == ControlState.HUMAN_ACTIVE
    assert store.snapshot.version == 2


@pytest.mark.asyncio
async def test_human_assumes_during_generation_before_outbox_and_blocks_gateway():
    store = InMemoryControlStore(snapshot())
    gate = InMemoryConversationGate()
    gateway = FakeWhatsAppGateway(
        SessionSnapshot(tenant_id=TENANT, session_id="pilot", owner_ref="owner", status=SessionStatus.CONNECTED, secure=True)
    )
    sender = SafeAutomaticSender(gateway, store, gate)
    generated = asyncio.Event()
    release = asyncio.Event()

    async def generation():
        generated.set()
        await release.wait()
        return outbound()

    task = asyncio.create_task(generation())
    await generated.wait()
    store.snapshot = snapshot(ControlState.HUMAN_ACTIVE, 2)
    release.set()
    with pytest.raises(AutomaticSendBlocked):
        await sender.send(await task)
    assert gateway.sent == {}


@pytest.mark.asyncio
async def test_second_re_read_during_outbox_prevents_send_after_human_takeover():
    store = InMemoryControlStore(snapshot())
    gate = InMemoryConversationGate()
    gateway = FakeWhatsAppGateway(
        SessionSnapshot(tenant_id=TENANT, session_id="pilot", owner_ref="owner", status=SessionStatus.CONNECTED, secure=True)
    )

    class TakeoverReader:
        def __init__(self):
            self.calls = 0

        async def read(self, tenant_id, conversation_id):
            self.calls += 1
            if self.calls == 2:
                store.snapshot = snapshot(ControlState.HUMAN_ACTIVE, 2)
            return await store.read(tenant_id, conversation_id)

    sender = SafeAutomaticSender(gateway, TakeoverReader(), gate)
    with pytest.raises(AutomaticSendBlocked):
        await sender.send(outbound())
    assert gateway.sent == {}


@pytest.mark.asyncio
async def test_bot_active_outbox_sends_and_assisted_formatter_preserves_facts():
    store = InMemoryControlStore(snapshot())
    gateway = FakeWhatsAppGateway(
        SessionSnapshot(tenant_id=TENANT, session_id="pilot", owner_ref="owner", status=SessionStatus.CONNECTED, secure=True)
    )
    sent = await SafeAutomaticSender(gateway, store, InMemoryConversationGate()).send(outbound())
    assert sent.status == "SENT"
    formatter = DeterministicAssistedFormatter()
    draft = await formatter.format("fato fornecido pelo humano", "formal")
    assert draft.content == "fato fornecido pelo humano"
    assert draft.policy_version == "control-v1"


@pytest.mark.asyncio
async def test_outbox_fails_closed_without_control_aware_sender():
    gateway = FakeWhatsAppGateway(
        SessionSnapshot(tenant_id=TENANT, session_id="pilot", owner_ref="owner", status=SessionStatus.CONNECTED, secure=True)
    )

    class Store:
        async def mark_delivered(self, idempotency_key, receipt):
            raise AssertionError("não deve marcar entrega")

    with pytest.raises(UnsafeSessionError):
        await OutboxDispatcher(gateway, Store()).dispatch(outbound())


@pytest.mark.asyncio
async def test_control_event_publisher_returns_only_sanitized_transition_metadata():
    from src.control import InMemoryControlEventPublisher
    from src.control.state_machine import ControlEvent

    publisher = InMemoryControlEventPublisher()
    event = ControlEvent(
        event_id=uuid4(), tenant_id=TENANT, conversation_id=CONVERSATION,
        previous_state=ControlState.BOT_ACTIVE, state=ControlState.HUMAN_ACTIVE,
        version=2, actor_user_id=None, reason="owner requested", policy_version="control-v1",
        occurred_at=datetime.now(timezone.utc),
    )
    await publisher.publish(event)
    assert publisher.events == [event]
    assert event.payload()["state"] == "HUMAN_ACTIVE"
    assert event.payload()["version"] == 2
