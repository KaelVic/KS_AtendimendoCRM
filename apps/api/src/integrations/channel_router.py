"""Tenant-scoped gateway routing with leases and fencing tokens.

The router is deliberately outside the WhatsAppAdapter contract.  It selects
one adapter only after re-reading the persisted ownership record, so a stale
worker cannot deliver through a session that was reassigned.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db.models import AuditEvent, ChannelSession, GatewayShard, SessionAssignment
from .whatsapp import GatewayReceipt, OutboundMessage, SessionSnapshot, SessionStatus, WhatsAppAdapter

logger = logging.getLogger("ks_channel_router")

DEFAULT_LEASE_SECONDS = 30
ROUTABLE_SHARD_STATUS = "HEALTHY"
VALID_SHARD_STATUSES = {"HEALTHY", "DEGRADED", "UNAVAILABLE", "DRAINING", "DISABLED"}


class ChannelRoutingError(RuntimeError):
    """Base error for a route that must fail closed."""


class TenantMismatchError(ChannelRoutingError):
    pass


class ShardUnavailableError(ChannelRoutingError):
    pass


class LeaseExpiredError(ChannelRoutingError):
    pass


class SplitBrainError(ChannelRoutingError):
    pass


class MigrationBlockedError(ChannelRoutingError):
    pass


@dataclass(frozen=True)
class RouteLease:
    tenant_id: UUID
    gateway_id: UUID
    external_session_id: str
    engine: str
    owner_id: str
    owner_epoch: int
    lease_expires_at: datetime
    assignment_version: int


@dataclass(frozen=True)
class ShardHealth:
    gateway_id: UUID
    tenant_id: UUID
    status: str
    engine: str
    version: str
    checked_at: datetime | None
    message: str | None = None


@dataclass(frozen=True)
class MigrationPreconditions:
    sending_paused: bool
    outbox_drained: bool
    backup_verified: bool
    previous_owner_stopped: bool
    restore_or_relink_verified: bool
    smoke_test_passed: bool

    def is_complete(self) -> bool:
        return all(
            (
                self.sending_paused,
                self.outbox_drained,
                self.backup_verified,
                self.previous_owner_stopped,
                self.restore_or_relink_verified,
                self.smoke_test_passed,
            )
        )


class RoutingBackend(Protocol):
    async def provision(
        self,
        tenant_id: UUID,
        gateway_id: UUID,
        external_session_id: str,
        *,
        engine: str,
        engine_version: str,
    ) -> None: ...

    async def claim(self, tenant_id: UUID, external_session_id: str, owner_id: str) -> RouteLease: ...

    async def resolve(self, tenant_id: UUID, external_session_id: str, owner_id: str) -> RouteLease: ...

    async def assert_fence(self, lease: RouteLease) -> None: ...

    async def renew(self, lease: RouteLease) -> RouteLease: ...

    async def release(self, lease: RouteLease) -> None: ...

    async def set_health(self, gateway_id: UUID, status: str, message: str | None = None) -> None: ...

    async def health(self, tenant_id: UUID | None = None) -> list[ShardHealth]: ...

    async def begin_migration(self, tenant_id: UUID, external_session_id: str) -> None: ...

    async def set_session_status(
        self, tenant_id: UUID, external_session_id: str, status: str, message: str | None = None
    ) -> None: ...


class ChannelRouter(WhatsAppAdapter):
    """Routes WhatsApp sends without changing the adapter interface."""

    def __init__(
        self,
        backend: RoutingBackend,
        adapters: dict[UUID, WhatsAppAdapter],
        *,
        owner_id: str,
        default_tenant_id: UUID | None = None,
        default_session_id: str | None = None,
    ) -> None:
        if not owner_id or len(owner_id) > 255:
            raise ValueError("owner_id inválido")
        self.backend = backend
        self.adapters = adapters
        self.owner_id = owner_id
        self.default_tenant_id = default_tenant_id
        self.default_session_id = default_session_id

    async def claim_session(self, tenant_id: UUID, external_session_id: str) -> RouteLease:
        lease = await self.backend.claim(tenant_id, external_session_id, self.owner_id)
        adapter = self._adapter_for(lease)
        # Ownership does not imply a connected WhatsApp session. Persist the
        # observed state before any send can pass the router.
        try:
            snapshot = await adapter.session()
            await self.backend.set_session_status(
                tenant_id,
                external_session_id,
                snapshot.status.value,
                None if snapshot.status.value == "CONNECTED" else snapshot.status.value,
            )
        except Exception as exc:
            await self.backend.set_session_status(
                tenant_id, external_session_id, "ERROR", type(exc).__name__
            )
        return lease

    async def provision_pilot(
        self,
        tenant_id: UUID,
        gateway_id: UUID,
        external_session_id: str,
        *,
        engine: str = "OPENWA",
        engine_version: str = "v0.23.3",
    ) -> None:
        await self.backend.provision(
            tenant_id,
            gateway_id,
            external_session_id,
            engine=engine,
            engine_version=engine_version,
        )

    async def renew_session(self, lease: RouteLease) -> RouteLease:
        self._check_owner(lease)
        return await self.backend.renew(lease)

    async def release_session(self, lease: RouteLease) -> None:
        self._check_owner(lease)
        await self.backend.release(lease)

    async def migrate_session(
        self,
        tenant_id: UUID,
        external_session_id: str,
        new_owner_id: str,
        preconditions: MigrationPreconditions,
    ) -> None:
        if not preconditions.is_complete():
            raise MigrationBlockedError("pré-condições de migração incompletas")
        await self.backend.begin_migration(tenant_id, external_session_id)
        # The new owner must explicitly claim after the old owner is fenced.
        # No connection is started here; relink/restore remains an operator step.
        lease = await self.backend.claim(tenant_id, external_session_id, new_owner_id)
        try:
            snapshot = await self._adapter_for(lease).session()
            await self.backend.set_session_status(
                tenant_id,
                external_session_id,
                snapshot.status.value,
                None if snapshot.status.value == "CONNECTED" else snapshot.status.value,
            )
        except Exception as exc:
            await self.backend.set_session_status(
                tenant_id, external_session_id, "ERROR", type(exc).__name__
            )

    async def prepare_outbox(self, message: OutboundMessage) -> RouteLease:
        """Resolve before an outbox row is created; never trusts client routing."""
        return await self.resolve_for_send(message)

    async def resolve_for_send(self, message: OutboundMessage) -> RouteLease:
        lease = await self.backend.resolve(
            message.tenant_id, message.session_id, self.owner_id
        )
        if lease.tenant_id != message.tenant_id:
            raise TenantMismatchError("tenant divergente")
        if lease.external_session_id != message.session_id:
            raise TenantMismatchError("sessão divergente")
        self._adapter_for(lease)
        return lease

    async def send(self, message: OutboundMessage) -> GatewayReceipt:
        lease = await self.resolve_for_send(message)
        # This second read is the fencing gate immediately before the external
        # side effect.  A lease obtained before a reassignment is unusable.
        await self.backend.assert_fence(lease)
        adapter = self._adapter_for(lease)
        try:
            return await adapter.send(message)
        except Exception as exc:
            await self.backend.set_health(lease.gateway_id, "UNAVAILABLE", type(exc).__name__)
            logger.warning(
                "channel_route_delivery_failed gateway=%s error=%s",
                lease.gateway_id,
                type(exc).__name__,
            )
            raise

    async def health(self) -> dict[str, Any]:
        shards = await self.backend.health()
        return {
            "status": "healthy" if shards and all(s.status == ROUTABLE_SHARD_STATUS for s in shards) else "unhealthy",
            "shards": [
                {
                    "gateway_id": str(shard.gateway_id),
                    "tenant_id": str(shard.tenant_id),
                    "status": shard.status,
                    "engine": shard.engine,
                    "version": shard.version,
                    "checked_at": shard.checked_at.isoformat() if shard.checked_at else None,
                    "message": shard.message,
                }
                for shard in shards
            ],
        }

    async def health_shards(self, tenant_id: UUID | None = None) -> list[ShardHealth]:
        return await self.backend.health(tenant_id)

    async def session(self) -> SessionSnapshot:
        if self.default_tenant_id is None or self.default_session_id is None:
            raise ChannelRoutingError("sessão padrão do router não configurada")
        lease = await self.backend.resolve(
            self.default_tenant_id, self.default_session_id, self.owner_id
        )
        await self.backend.assert_fence(lease)
        snapshot = await self._adapter_for(lease).session()
        if snapshot.tenant_id != lease.tenant_id or snapshot.session_id != lease.external_session_id:
            raise TenantMismatchError("snapshot do gateway divergente")
        return snapshot

    def _adapter_for(self, lease: RouteLease) -> WhatsAppAdapter:
        try:
            return self.adapters[lease.gateway_id]
        except KeyError as exc:
            raise ShardUnavailableError("adapter do shard não configurado") from exc

    def _check_owner(self, lease: RouteLease) -> None:
        if lease.owner_id != self.owner_id:
            raise SplitBrainError("owner divergente")


@dataclass
class _MemoryShard:
    gateway_id: UUID
    tenant_id: UUID
    engine: str
    version: str
    status: str = "HEALTHY"
    owner_epoch: int = 0
    checked_at: datetime | None = None
    message: str | None = None


@dataclass
class _MemorySession:
    tenant_id: UUID
    gateway_id: UUID
    external_session_id: str
    engine: str
    version: int = 1
    status: str = "CONNECTED"
    owner_epoch: int = 0


@dataclass
class _MemoryAssignment:
    lease: RouteLease
    status: str = "ACTIVE"
    version: int = 1


class InMemoryRoutingBackend:
    """Deterministic backend used by unit and concurrency tests."""

    def __init__(self, *, lease_seconds: int = DEFAULT_LEASE_SECONDS, clock: Any | None = None) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds deve ser positivo")
        self.lease_seconds = lease_seconds
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.shards: dict[UUID, _MemoryShard] = {}
        self.sessions: dict[tuple[UUID, str], _MemorySession] = {}
        self.assignments: dict[tuple[UUID, str], _MemoryAssignment] = {}
        self.audit: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    async def register_shard(
        self, tenant_id: UUID, gateway_id: UUID, *, engine: str = "OPENWA", version: str = "v0.23.3"
    ) -> None:
        async with self._lock:
            self.shards[gateway_id] = _MemoryShard(gateway_id, tenant_id, engine, version)

    async def provision(
        self,
        tenant_id: UUID,
        gateway_id: UUID,
        external_session_id: str,
        *,
        engine: str,
        engine_version: str,
    ) -> None:
        async with self._lock:
            existing_shard = self.shards.get(gateway_id)
            if existing_shard and existing_shard.tenant_id != tenant_id:
                raise TenantMismatchError("shard não pertence ao tenant")
            if not existing_shard:
                self.shards[gateway_id] = _MemoryShard(
                    gateway_id, tenant_id, engine, engine_version, status="DISABLED"
                )
            existing_session = self.sessions.get((tenant_id, external_session_id))
            if existing_session and existing_session.gateway_id != gateway_id:
                raise ChannelRoutingError("sessão já atribuída a outro shard")
            if not existing_session:
                self.sessions[(tenant_id, external_session_id)] = _MemorySession(
                    tenant_id,
                    gateway_id,
                    external_session_id,
                    engine,
                    status="DISCONNECTED",
                )
            self._audit_locked(
                tenant_id,
                "CHANNEL_PILOT_PROVISIONED",
                self.sessions[(tenant_id, external_session_id)],
                "system",
            )

    async def register_session(
        self,
        tenant_id: UUID,
        gateway_id: UUID,
        external_session_id: str,
        *,
        engine: str = "OPENWA",
        status: str = "CONNECTED",
    ) -> None:
        async with self._lock:
            shard = self.shards.get(gateway_id)
            if shard is None or shard.tenant_id != tenant_id:
                raise TenantMismatchError("shard não pertence ao tenant")
            self.sessions[(tenant_id, external_session_id)] = _MemorySession(
                tenant_id, gateway_id, external_session_id, engine, status=status
            )

    async def set_session_status(
        self, tenant_id: UUID, external_session_id: str, status: str, message: str | None = None
    ) -> None:
        if status not in {value.value for value in SessionStatus}:
            raise ValueError("status de sessão inválido")
        async with self._lock:
            session = self._session_locked(tenant_id, external_session_id)
            session.status = status
            session.version += 1
            self._audit_locked(tenant_id, "SESSION_STATUS_UPDATED", session, message or "system")

    async def claim(self, tenant_id: UUID, external_session_id: str, owner_id: str) -> RouteLease:
        async with self._lock:
            session = self._session_locked(tenant_id, external_session_id)
            shard = self.shards[session.gateway_id]
            now = self.clock()
            current = self.assignments.get((tenant_id, external_session_id))
            if current and current.status == "ACTIVE":
                if current.lease.lease_expires_at > now:
                    if current.lease.owner_id != owner_id:
                        raise SplitBrainError("sessão já possui owner ativo")
                    return current.lease
                current.status = "FENCED"
                self._audit_locked(tenant_id, "SESSION_ASSIGNMENT_FENCED", session, current.lease.owner_id)
            self._ensure_shard_locked(shard)
            epoch = max(session.owner_epoch, shard.owner_epoch, current.lease.owner_epoch if current else 0) + 1
            expires = now + timedelta(seconds=self.lease_seconds)
            lease = RouteLease(tenant_id, shard.gateway_id, external_session_id, session.engine, owner_id, epoch, expires, 1)
            self.assignments[(tenant_id, external_session_id)] = _MemoryAssignment(lease)
            session.owner_epoch = epoch
            session.version += 1
            shard.owner_epoch = max(shard.owner_epoch, epoch)
            self._audit_locked(tenant_id, "SESSION_ASSIGNED", session, owner_id)
            return lease

    async def resolve(self, tenant_id: UUID, external_session_id: str, owner_id: str) -> RouteLease:
        async with self._lock:
            session = self._session_locked(tenant_id, external_session_id)
            shard = self.shards[session.gateway_id]
            assignment = self.assignments.get((tenant_id, external_session_id))
            now = self.clock()
            self._ensure_shard_locked(shard)
            if not assignment or assignment.status != "ACTIVE":
                raise LeaseExpiredError("sessão sem owner ativo")
            if assignment.lease.owner_id != owner_id:
                raise SplitBrainError("owner divergente")
            if assignment.lease.lease_expires_at <= now:
                assignment.status = "EXPIRED"
                raise LeaseExpiredError("lease expirado")
            if session.owner_epoch != assignment.lease.owner_epoch:
                raise LeaseExpiredError("fencing token da sessão expirado")
            if session.status != "CONNECTED":
                raise ShardUnavailableError("sessão não está conectada")
            return assignment.lease

    async def assert_fence(self, lease: RouteLease) -> None:
        async with self._lock:
            session = self._session_locked(lease.tenant_id, lease.external_session_id)
            assignment = self.assignments.get((lease.tenant_id, lease.external_session_id))
            now = self.clock()
            if (
                not assignment
                or assignment.status != "ACTIVE"
                or assignment.lease.owner_id != lease.owner_id
                or assignment.lease.owner_epoch != lease.owner_epoch
                or assignment.lease.lease_expires_at <= now
                or session.owner_epoch != lease.owner_epoch
            ):
                raise LeaseExpiredError("fencing token inválido")
            self._ensure_shard_locked(self.shards[session.gateway_id])

    async def renew(self, lease: RouteLease) -> RouteLease:
        async with self._lock:
            return self._renew_locked(lease)

    async def release(self, lease: RouteLease) -> None:
        async with self._lock:
            assignment = self.assignments.get((lease.tenant_id, lease.external_session_id))
            if not assignment or assignment.lease.owner_epoch != lease.owner_epoch or assignment.lease.owner_id != lease.owner_id:
                raise LeaseExpiredError("não é possível liberar lease antigo")
            assignment.status = "RELEASED"
            self._audit_locked(lease.tenant_id, "SESSION_RELEASED", self._session_locked(lease.tenant_id, lease.external_session_id), lease.owner_id)

    async def set_health(self, gateway_id: UUID, status: str, message: str | None = None) -> None:
        if status not in VALID_SHARD_STATUSES:
            raise ValueError("status de shard inválido")
        async with self._lock:
            shard = self.shards[gateway_id]
            shard.status = status
            shard.checked_at = self.clock()
            shard.message = message
            if status != ROUTABLE_SHARD_STATUS:
                for key, assignment in self.assignments.items():
                    session = self.sessions[key]
                    if session.gateway_id == gateway_id and assignment.status == "ACTIVE":
                        assignment.status = "FENCED"
                        session.status = "UNAVAILABLE"
                        session.owner_epoch += 1
                        self._audit_locked(session.tenant_id, "SHARD_HEALTH_FENCED_SESSION", session, assignment.lease.owner_id)

    async def health(self, tenant_id: UUID | None = None) -> list[ShardHealth]:
        async with self._lock:
            return [
                ShardHealth(s.gateway_id, s.tenant_id, s.status, s.engine, s.version, s.checked_at, s.message)
                for s in self.shards.values()
                if tenant_id is None or s.tenant_id == tenant_id
            ]

    async def begin_migration(self, tenant_id: UUID, external_session_id: str) -> None:
        async with self._lock:
            session = self._session_locked(tenant_id, external_session_id)
            assignment = self.assignments.get((tenant_id, external_session_id))
            if assignment and assignment.status == "ACTIVE":
                assignment.status = "MIGRATING"
                session.owner_epoch += 1
                session.status = "MIGRATING"
                self._audit_locked(tenant_id, "SESSION_MIGRATION_STARTED", session, assignment.lease.owner_id)

    def _renew_locked(self, lease: RouteLease) -> RouteLease:
        assignment = self.assignments.get((lease.tenant_id, lease.external_session_id))
        session = self._session_locked(lease.tenant_id, lease.external_session_id)
        now = self.clock()
        if not assignment or assignment.status != "ACTIVE" or assignment.lease.owner_epoch != lease.owner_epoch or assignment.lease.owner_id != lease.owner_id or assignment.lease.lease_expires_at <= now:
            raise LeaseExpiredError("lease expirado")
        renewed = RouteLease(lease.tenant_id, lease.gateway_id, lease.external_session_id, lease.engine, lease.owner_id, lease.owner_epoch, now + timedelta(seconds=self.lease_seconds), assignment.version + 1)
        assignment.lease = renewed
        assignment.version += 1
        session.version += 1
        self._audit_locked(lease.tenant_id, "SESSION_LEASE_RENEWED", session, lease.owner_id)
        return renewed

    def _session_locked(self, tenant_id: UUID, external_session_id: str) -> _MemorySession:
        session = self.sessions.get((tenant_id, external_session_id))
        if session is None:
            if any(ext == external_session_id for _, ext in self.sessions):
                raise TenantMismatchError("sessão pertence a outro tenant")
            raise ChannelRoutingError("sessão não encontrada")
        return session

    @staticmethod
    def _ensure_shard_locked(shard: _MemoryShard) -> None:
        if shard.status != ROUTABLE_SHARD_STATUS:
            raise ShardUnavailableError("shard indisponível")

    def _audit_locked(self, tenant_id: UUID, action: str, session: _MemorySession, owner_id: str) -> None:
        self.audit.append({"tenant_id": tenant_id, "action": action, "session_id": session.external_session_id, "gateway_id": session.gateway_id, "owner_id": owner_id, "owner_epoch": session.owner_epoch})


class SqlAlchemyRoutingBackend:
    """PostgreSQL implementation; row locks and the partial unique index fence races."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        clock: Any | None = None,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds deve ser positivo")
        self.session_factory = session_factory
        self.lease_seconds = lease_seconds
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def claim(self, tenant_id: UUID, external_session_id: str, owner_id: str) -> RouteLease:
        now = self.clock()
        async with self.session_factory() as db:
            async with db.begin():
                session = await db.scalar(
                    select(ChannelSession)
                    .where(ChannelSession.tenant_id == tenant_id, ChannelSession.external_session_id == external_session_id)
                    .with_for_update()
                )
                if session is None:
                    other = await db.scalar(select(ChannelSession).where(ChannelSession.external_session_id == external_session_id))
                    if other:
                        raise TenantMismatchError("sessão pertence a outro tenant")
                    raise ChannelRoutingError("sessão não encontrada")
                shard = await db.scalar(
                    select(GatewayShard)
                    .where(GatewayShard.tenant_id == tenant_id, GatewayShard.gateway_id == session.gateway_id)
                    .with_for_update()
                )
                if shard is None:
                    raise ShardUnavailableError("shard não encontrado")
                self._ensure_shard(shard)
                assignment = await db.scalar(
                    select(SessionAssignment)
                    .where(
                        SessionAssignment.tenant_id == tenant_id,
                        SessionAssignment.external_session_id == external_session_id,
                        SessionAssignment.status == "ACTIVE",
                    )
                    .with_for_update()
                )
                if assignment and assignment.lease_expires_at > now:
                    if assignment.owner_id != owner_id:
                        raise SplitBrainError("sessão já possui owner ativo")
                    return self._lease(session, assignment)
                if assignment:
                    assignment.status = "FENCED"
                    await self._audit(db, tenant_id, "SESSION_ASSIGNMENT_FENCED", session.id, owner_id, assignment.owner_epoch)
                epoch = max(session.owner_epoch, shard.owner_epoch, assignment.owner_epoch if assignment else 0) + 1
                expires = now + timedelta(seconds=self.lease_seconds)
                assignment = SessionAssignment(
                    id=uuid4(), tenant_id=tenant_id, gateway_id=shard.gateway_id,
                    external_session_id=external_session_id, engine=shard.engine, owner_id=owner_id,
                    status="ACTIVE", owner_epoch=epoch, lease_expires_at=expires,
                    version=1, acquired_at=now, created_at=now, updated_at=now,
                )
                db.add(assignment)
                session.owner_epoch = epoch
                session.version += 1
                shard.owner_epoch = max(shard.owner_epoch, epoch)
                session.updated_at = now
                shard.updated_at = now
                await self._audit(db, tenant_id, "SESSION_ASSIGNED", session.id, owner_id, epoch)
                return self._lease(session, assignment)

    async def provision(
        self,
        tenant_id: UUID,
        gateway_id: UUID,
        external_session_id: str,
        *,
        engine: str,
        engine_version: str,
    ) -> None:
        now = self.clock()
        async with self.session_factory() as db:
            async with db.begin():
                shard = await db.scalar(
                    select(GatewayShard)
                    .where(GatewayShard.gateway_id == gateway_id)
                    .with_for_update()
                )
                if shard is None:
                    shard = GatewayShard(
                        gateway_id=gateway_id,
                        tenant_id=tenant_id,
                        engine=engine,
                        status="DISABLED",
                        owner_epoch=0,
                        version=1,
                        engine_version=engine_version,
                        created_at=now,
                        updated_at=now,
                    )
                    db.add(shard)
                elif shard.tenant_id != tenant_id:
                    raise TenantMismatchError("shard não pertence ao tenant")
                session = await db.scalar(
                    select(ChannelSession)
                    .where(
                        ChannelSession.tenant_id == tenant_id,
                        ChannelSession.external_session_id == external_session_id,
                    )
                    .with_for_update()
                )
                if session and session.gateway_id != gateway_id:
                    raise ChannelRoutingError("sessão já atribuída a outro shard")
                if session is None:
                    db.add(
                        ChannelSession(
                            id=uuid4(),
                            tenant_id=tenant_id,
                            gateway_id=gateway_id,
                            external_session_id=external_session_id,
                            engine=engine,
                            status="DISCONNECTED",
                            owner_epoch=0,
                            version=1,
                            engine_version=engine_version,
                            metadata_json={},
                            created_at=now,
                            updated_at=now,
                        )
                    )

    async def resolve(self, tenant_id: UUID, external_session_id: str, owner_id: str) -> RouteLease:
        async with self.session_factory() as db:
            session = await db.scalar(select(ChannelSession).where(ChannelSession.tenant_id == tenant_id, ChannelSession.external_session_id == external_session_id))
            if session is None:
                other = await db.scalar(select(ChannelSession).where(ChannelSession.external_session_id == external_session_id))
                if other:
                    raise TenantMismatchError("sessão pertence a outro tenant")
                raise ChannelRoutingError("sessão não encontrada")
            shard = await db.scalar(select(GatewayShard).where(GatewayShard.tenant_id == tenant_id, GatewayShard.gateway_id == session.gateway_id))
            assignment = await db.scalar(select(SessionAssignment).where(SessionAssignment.tenant_id == tenant_id, SessionAssignment.external_session_id == external_session_id, SessionAssignment.status == "ACTIVE"))
            if shard is None:
                raise ShardUnavailableError("shard não encontrado")
            self._ensure_shard(shard)
            if assignment is None or assignment.owner_id != owner_id:
                raise SplitBrainError("owner divergente ou ausente")
            if assignment.lease_expires_at <= self.clock():
                raise LeaseExpiredError("lease expirado")
            if session.owner_epoch != assignment.owner_epoch:
                raise LeaseExpiredError("fencing token da sessão expirado")
            if session.status != "CONNECTED":
                raise ShardUnavailableError("sessão não está conectada")
            return self._lease(session, assignment)

    async def assert_fence(self, lease: RouteLease) -> None:
        current = await self.resolve(lease.tenant_id, lease.external_session_id, lease.owner_id)
        if current.owner_epoch != lease.owner_epoch or current.gateway_id != lease.gateway_id:
            raise LeaseExpiredError("fencing token inválido")

    async def set_session_status(
        self, tenant_id: UUID, external_session_id: str, status: str, message: str | None = None
    ) -> None:
        if status not in {value.value for value in SessionStatus}:
            raise ValueError("status de sessão inválido")
        now = self.clock()
        async with self.session_factory() as db:
            async with db.begin():
                session = await db.scalar(
                    select(ChannelSession)
                    .where(
                        ChannelSession.tenant_id == tenant_id,
                        ChannelSession.external_session_id == external_session_id,
                    )
                    .with_for_update()
                )
                if session is None:
                    raise ChannelRoutingError("sessão não encontrada")
                session.status = status
                session.last_failure_code = (
                    message[:80] if message and status != "CONNECTED" else None
                )
                session.version += 1
                session.updated_at = now
                await self._audit(
                    db,
                    tenant_id,
                    "SESSION_STATUS_UPDATED",
                    session.id,
                    "system",
                    session.owner_epoch,
                )

    async def renew(self, lease: RouteLease) -> RouteLease:
        now = self.clock()
        async with self.session_factory() as db:
            async with db.begin():
                assignment = await db.scalar(select(SessionAssignment).where(SessionAssignment.tenant_id == lease.tenant_id, SessionAssignment.external_session_id == lease.external_session_id, SessionAssignment.status == "ACTIVE").with_for_update())
                if assignment is None or assignment.owner_id != lease.owner_id or assignment.owner_epoch != lease.owner_epoch or assignment.lease_expires_at <= now:
                    raise LeaseExpiredError("lease expirado")
                assignment.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
                assignment.version += 1
                assignment.updated_at = now
                return RouteLease(lease.tenant_id, lease.gateway_id, lease.external_session_id, lease.engine, lease.owner_id, lease.owner_epoch, assignment.lease_expires_at, assignment.version)

    async def release(self, lease: RouteLease) -> None:
        now = self.clock()
        async with self.session_factory() as db:
            async with db.begin():
                assignment = await db.scalar(select(SessionAssignment).where(SessionAssignment.tenant_id == lease.tenant_id, SessionAssignment.external_session_id == lease.external_session_id, SessionAssignment.status == "ACTIVE").with_for_update())
                if assignment is None or assignment.owner_id != lease.owner_id or assignment.owner_epoch != lease.owner_epoch:
                    raise LeaseExpiredError("lease antigo")
                assignment.status = "RELEASED"
                assignment.released_at = now
                assignment.version += 1
                assignment.updated_at = now
                await self._audit(db, lease.tenant_id, "SESSION_RELEASED", None, lease.owner_id, lease.owner_epoch)

    async def set_health(self, gateway_id: UUID, status: str, message: str | None = None) -> None:
        if status not in VALID_SHARD_STATUSES:
            raise ValueError("status de shard inválido")
        now = self.clock()
        async with self.session_factory() as db:
            async with db.begin():
                shard = await db.scalar(select(GatewayShard).where(GatewayShard.gateway_id == gateway_id).with_for_update())
                if shard is None:
                    raise ShardUnavailableError("shard não encontrado")
                shard.status, shard.health_message, shard.last_health_at, shard.updated_at = status, message, now, now
                if status != ROUTABLE_SHARD_STATUS:
                    sessions = (await db.scalars(select(ChannelSession).where(ChannelSession.gateway_id == gateway_id).with_for_update())).all()
                    for session in sessions:
                        session.status = "UNAVAILABLE"
                        session.last_failure_code = message or "SHARD_UNAVAILABLE"
                        session.owner_epoch += 1
                        session.version += 1
                        await db.execute(update(SessionAssignment).where(SessionAssignment.tenant_id == session.tenant_id, SessionAssignment.external_session_id == session.external_session_id, SessionAssignment.status == "ACTIVE").values(status="FENCED", updated_at=now))
                        await self._audit(db, session.tenant_id, "SHARD_HEALTH_FENCED_SESSION", session.id, "system", session.owner_epoch)

    async def health(self, tenant_id: UUID | None = None) -> list[ShardHealth]:
        async with self.session_factory() as db:
            statement = select(GatewayShard)
            if tenant_id:
                statement = statement.where(GatewayShard.tenant_id == tenant_id)
            rows = (await db.scalars(statement.order_by(GatewayShard.tenant_id, GatewayShard.gateway_id))).all()
            return [ShardHealth(row.gateway_id, row.tenant_id, row.status, row.engine, row.engine_version, row.last_health_at, row.health_message) for row in rows]

    async def begin_migration(self, tenant_id: UUID, external_session_id: str) -> None:
        now = self.clock()
        async with self.session_factory() as db:
            async with db.begin():
                session = await db.scalar(select(ChannelSession).where(ChannelSession.tenant_id == tenant_id, ChannelSession.external_session_id == external_session_id).with_for_update())
                if session is None:
                    raise ChannelRoutingError("sessão não encontrada")
                assignment = await db.scalar(select(SessionAssignment).where(SessionAssignment.tenant_id == tenant_id, SessionAssignment.external_session_id == external_session_id, SessionAssignment.status == "ACTIVE").with_for_update())
                if assignment:
                    assignment.status = "MIGRATING"
                    assignment.updated_at = now
                session.owner_epoch += 1
                session.status = "MIGRATING"
                session.version += 1
                session.updated_at = now
                await self._audit(db, tenant_id, "SESSION_MIGRATION_STARTED", session.id, assignment.owner_id if assignment else "system", session.owner_epoch)

    @staticmethod
    def _ensure_shard(shard: GatewayShard) -> None:
        if shard.status != ROUTABLE_SHARD_STATUS:
            raise ShardUnavailableError("shard indisponível")

    @staticmethod
    def _lease(session: ChannelSession, assignment: SessionAssignment) -> RouteLease:
        return RouteLease(session.tenant_id, session.gateway_id, session.external_session_id, session.engine, assignment.owner_id, assignment.owner_epoch, assignment.lease_expires_at, assignment.version)

    @staticmethod
    async def _audit(db: AsyncSession, tenant_id: UUID, action: str, target_id: UUID | None, owner_id: str, epoch: int) -> None:
        db.add(AuditEvent(id=uuid4(), tenant_id=tenant_id, actor_user_id=None, action=action, target_type="channel_session", target_id=target_id, correlation_id=str(uuid4()), event_metadata={"owner_id": owner_id, "owner_epoch": epoch}))
