from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from src.integrations.channel_router import (
    ChannelRouter,
    InMemoryRoutingBackend,
    LeaseExpiredError,
    MigrationBlockedError,
    MigrationPreconditions,
    ShardUnavailableError,
    SplitBrainError,
    TenantMismatchError,
)
from src.integrations.whatsapp import FakeWhatsAppGateway, OutboxDispatcher, OutboundMessage, SessionSnapshot, SessionStatus
from src.integrations.whatsapp import SqlAlchemyOutboxStore


TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
GATEWAY = UUID("11111111-1111-1111-1111-111111111111")
SESSION = "pilot-session"


class Clock:
    def __init__(self) -> None:
        self.current = datetime(2026, 9, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


def message(tenant_id: UUID = TENANT_A, key: str = "route-1") -> OutboundMessage:
    return OutboundMessage(
        tenant_id=tenant_id,
        conversation_id=uuid4(),
        session_id=SESSION,
        recipient_ref="synthetic-recipient",
        content="mensagem sintética",
        idempotency_key=key,
    )


def router(backend: InMemoryRoutingBackend, owner_id: str) -> ChannelRouter:
    gateway = FakeWhatsAppGateway(
        SessionSnapshot(
            tenant_id=TENANT_A,
            session_id=SESSION,
            owner_ref="owner",
            status=SessionStatus.CONNECTED,
            secure=True,
        )
    )
    return ChannelRouter(backend, {GATEWAY: gateway}, owner_id=owner_id)


async def configured_backend(clock: Clock | None = None) -> InMemoryRoutingBackend:
    backend = InMemoryRoutingBackend(lease_seconds=10, clock=clock)
    await backend.register_shard(TENANT_A, GATEWAY)
    await backend.register_session(TENANT_A, GATEWAY, SESSION)
    return backend


@pytest.mark.asyncio
async def test_concurrent_claim_has_one_active_owner_and_fences_the_other() -> None:
    backend = await configured_backend()
    first, second = router(backend, "owner-a"), router(backend, "owner-b")

    results = await asyncio.gather(
        first.claim_session(TENANT_A, SESSION),
        second.claim_session(TENANT_A, SESSION),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, SplitBrainError) for result in results) == 1
    assert [event["action"] for event in backend.audit].count("SESSION_ASSIGNED") == 1


@pytest.mark.asyncio
async def test_expired_lease_gets_new_epoch_and_old_owner_cannot_send() -> None:
    clock = Clock()
    backend = await configured_backend(clock)
    first, second = router(backend, "owner-a"), router(backend, "owner-b")
    old_lease = await first.claim_session(TENANT_A, SESSION)
    clock.advance(11)

    with pytest.raises(LeaseExpiredError):
        await first.send(message())
    new_lease = await second.claim_session(TENANT_A, SESSION)

    assert new_lease.owner_epoch > old_lease.owner_epoch
    with pytest.raises(SplitBrainError):
        await first.send(message(key="stale-send"))


@pytest.mark.asyncio
async def test_unavailable_shard_fails_closed_before_adapter_delivery() -> None:
    backend = await configured_backend()
    gateway_router = router(backend, "owner-a")
    await gateway_router.claim_session(TENANT_A, SESSION)
    await backend.set_health(GATEWAY, "UNAVAILABLE", "health check failed")

    with pytest.raises(ShardUnavailableError):
        await gateway_router.send(message())

    assert (await gateway_router.health())["status"] == "unhealthy"


@pytest.mark.asyncio
async def test_claim_persists_gateway_relink_state_and_does_not_mark_ready() -> None:
    backend = await configured_backend()
    gateway = FakeWhatsAppGateway(
        SessionSnapshot(
            tenant_id=TENANT_A,
            session_id=SESSION,
            owner_ref="owner-a",
            status=SessionStatus.RELINK_REQUIRED,
            secure=False,
        )
    )
    gateway_router = ChannelRouter(backend, {GATEWAY: gateway}, owner_id="owner-a")

    await gateway_router.claim_session(TENANT_A, SESSION)

    assert backend.sessions[(TENANT_A, SESSION)].status == "RELINK_REQUIRED"
    with pytest.raises(ShardUnavailableError):
        await gateway_router.send(message(key="relink-blocked"))


@pytest.mark.asyncio
async def test_tenant_divergence_is_rejected_server_side() -> None:
    backend = await configured_backend()
    gateway_router = router(backend, "owner-a")
    await gateway_router.claim_session(TENANT_A, SESSION)

    with pytest.raises(TenantMismatchError):
        await gateway_router.send(message(tenant_id=TENANT_B))


@pytest.mark.asyncio
async def test_reassignment_fences_previous_owner_and_allows_new_owner() -> None:
    backend = await configured_backend()
    first, second = router(backend, "owner-a"), router(backend, "owner-b")
    old_lease = await first.claim_session(TENANT_A, SESSION)
    await first.release_session(old_lease)
    new_lease = await second.claim_session(TENANT_A, SESSION)

    assert new_lease.owner_epoch > old_lease.owner_epoch
    with pytest.raises(SplitBrainError):
        await first.send(message(key="old-owner"))
    receipt = await second.send(message(key="new-owner"))
    assert receipt.status == "SENT"


@pytest.mark.asyncio
async def test_migration_requires_pause_drain_backup_stop_restore_and_smoke() -> None:
    backend = await configured_backend()
    owner = router(backend, "owner-a")
    await owner.claim_session(TENANT_A, SESSION)
    incomplete = MigrationPreconditions(False, True, True, True, True, True)

    with pytest.raises(MigrationBlockedError):
        await owner.migrate_session(TENANT_A, SESSION, "owner-b", incomplete)

    complete = MigrationPreconditions(True, True, True, True, True, True)
    await owner.migrate_session(TENANT_A, SESSION, "owner-b", complete)
    assert "SESSION_MIGRATION_STARTED" in [event["action"] for event in backend.audit]
    with pytest.raises(SplitBrainError):
        await owner.send(message(key="fenced-owner"))
    assert (await router(backend, "owner-b").send(message(key="migrated-owner"))).status == "SENT"


@pytest.mark.asyncio
async def test_prepare_outbox_resolves_route_with_current_fencing_token() -> None:
    backend = await configured_backend()
    gateway_router = router(backend, "owner-a")
    await gateway_router.claim_session(TENANT_A, SESSION)

    lease = await gateway_router.prepare_outbox(message())

    assert lease.gateway_id == GATEWAY
    assert lease.external_session_id == SESSION
    assert lease.owner_epoch == 1


@pytest.mark.asyncio
async def test_outbox_persists_server_resolved_route_before_delivery() -> None:
    backend = await configured_backend()
    gateway_router = router(backend, "owner-a")
    await gateway_router.claim_session(TENANT_A, SESSION)

    class OutboxSession:
        row = None

        async def scalar(self, statement):
            return None

        def add(self, row) -> None:
            self.row = row

        async def commit(self) -> None:
            return None

    store = SqlAlchemyOutboxStore(OutboxSession(), router=gateway_router)
    await store.enqueue(message())

    assert store.session.row.payload["routing"] == {
        "gateway_id": str(GATEWAY),
        "external_session_id": SESSION,
        "owner_epoch": 1,
    }


@pytest.mark.asyncio
async def test_dispatcher_cannot_bypass_router_with_automatic_sender() -> None:
    backend = await configured_backend()
    gateway_router = router(backend, "owner-a")
    await gateway_router.claim_session(TENANT_A, SESSION)

    class Store:
        async def mark_delivered(self, idempotency_key, receipt) -> None:
            return None

    class Bypass:
        async def send(self, message):
            raise AssertionError("automatic sender bypassed ChannelRouter")

    receipt = await OutboxDispatcher(
        gateway_router,
        Store(),
        automatic_sender=Bypass(),
        router=gateway_router,
    ).dispatch(message())

    assert receipt.status == "SENT"
