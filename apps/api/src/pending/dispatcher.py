from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db.models import AuditEvent, PendingItem, PendingNotification
from .domain import window_index
from .email import EmailMessage, EmailProvider
from ..core.observability import record_integration

logger = logging.getLogger("ks_pending")
REMINDER_INTERVAL_SECONDS = 2 * 60 * 60


@dataclass(frozen=True)
class DispatchResult:
    notification_id: UUID | None
    status: str
    attempts: int = 0


class PendingNotificationDispatcher:
    """Claims and sends one due reminder per invocation.

    The claim is a PostgreSQL row lock plus a short lease. Thus two workers
    cannot send the same window, and a worker that dies can be recovered after
    the lease expires. Only the newest elapsed window is materialized after a
    downtime, avoiding a reminder avalanche.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        provider: EmailProvider,
        owner_alert_email: str,
        *,
        clock: Callable[[], datetime] | None = None,
        send_timeout_seconds: float = 10.0,
        lease_seconds: int = 60,
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.owner_alert_email = owner_alert_email
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.send_timeout_seconds = send_timeout_seconds
        self.lease_seconds = lease_seconds

    async def dispatch_once(self, tenant_id: UUID | None = None) -> DispatchResult:
        now = self.clock()
        async with self.session_factory() as session:
            await self._materialize_latest_windows(session, now, tenant_id)
            claim = cast(
                tuple[UUID, UUID, str, int, int] | None,
                await self._claim(session, now, tenant_id),
            )
        if claim is None:
            return DispatchResult(None, "IDLE")
        notification_id: UUID = claim[0]
        pending_id: UUID = claim[1]
        kind: str = claim[2]
        attempts: int = claim[3]
        current_window: int = claim[4]

        if not self.owner_alert_email.strip():
            await self._fail(
                notification_id,
                "OWNER_ALERT_EMAIL_NOT_CONFIGURED",
                now,
                retry_after_seconds=REMINDER_INTERVAL_SECONDS,
            )
            return DispatchResult(notification_id, "FAILED", attempts)

        async with self.session_factory() as session:
            still_open = await session.scalar(
                select(PendingItem.id).where(
                    PendingItem.id == pending_id,
                    PendingItem.status == "OPEN",
                )
            )
        if still_open is None:
            await self._cancel(notification_id, now)
            return DispatchResult(notification_id, "CANCELLED", attempts)

        message = EmailMessage(
            to=self.owner_alert_email,
            subject=f"Ação pendente no CRM: {kind}",
            body="Há uma pendência aguardando ação. Abra o CRM para revisar e responder.",
            idempotency_key=f"pending:{pending_id}:window:{current_window}",
        )
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                self.provider.send(message), timeout=self.send_timeout_seconds
            )
        except Exception as exc:
            record_integration("email", "error", (time.perf_counter() - started) * 1000)
            await self._fail(notification_id, type(exc).__name__, now)
            return DispatchResult(notification_id, "FAILED", attempts)

        record_integration("email", "success", (time.perf_counter() - started) * 1000)
        await self._mark_sent(notification_id, result.message_id, now)
        return DispatchResult(notification_id, "SENT", attempts)

    async def _materialize_latest_windows(
        self, session: AsyncSession, now: datetime, tenant_id: UUID | None
    ) -> None:
        query = select(PendingItem).where(PendingItem.status == "OPEN")
        if tenant_id:
            query = query.where(PendingItem.tenant_id == tenant_id)
        items = list(await session.scalars(query))
        for item in items:
            current_window = window_index(item.created_at, now)
            latest = await session.scalar(
                select(PendingNotification)
                .where(
                    PendingNotification.tenant_id == item.tenant_id,
                    PendingNotification.pending_item_id == item.id,
                )
                .order_by(PendingNotification.window_index.desc())
            )
            if latest is not None and latest.window_index >= current_window:
                continue
            # A failed/processing prior window is retried before a later one is
            # materialized, preventing a downtime burst and preserving order.
            if latest is not None and latest.status not in {"SENT", "CANCELLED"}:
                continue
            values = {
                "id": uuid4(),
                "tenant_id": item.tenant_id,
                "pending_item_id": item.id,
                "window_index": current_window,
                "idempotency_key": f"pending:{item.id}:window:{current_window}",
                "correlation_id": str(uuid4()),
                "status": "PENDING",
                "attempts": 0,
                "next_attempt_at": now,
                "created_at": now,
                "updated_at": now,
            }
            await session.execute(
                insert(PendingNotification)
                .values(**values)
                .on_conflict_do_nothing(
                    constraint="uq_pending_notifications_window"
                )
            )
        await session.commit()

    async def _claim(
        self, session: AsyncSession, now: datetime, tenant_id: UUID | None
    ) -> tuple[UUID, UUID, str, int, int] | None:
        query = (
            select(PendingNotification, PendingItem)
            .join(
                PendingItem,
                (PendingItem.id == PendingNotification.pending_item_id)
                & (PendingItem.tenant_id == PendingNotification.tenant_id),
            )
            .where(
                PendingItem.status == "OPEN",
                or_(
                    and_(
                        PendingNotification.status.in_(["PENDING", "FAILED"]),
                        or_(
                            PendingNotification.next_attempt_at.is_(None),
                            PendingNotification.next_attempt_at <= now,
                        ),
                    ),
                    and_(
                        PendingNotification.status == "PROCESSING",
                        PendingNotification.locked_until < now,
                    ),
                ),
            )
            .order_by(PendingNotification.created_at, PendingNotification.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if tenant_id:
            query = query.where(PendingNotification.tenant_id == tenant_id)
        row = (await session.execute(query)).first()
        if row is None:
            return None
        notification, item = row
        notification.status = "PROCESSING"
        notification.attempts += 1
        notification.locked_until = now + timedelta(seconds=self.lease_seconds)
        notification.updated_at = now
        await session.commit()
        return notification.id, item.id, item.kind, notification.attempts, notification.window_index

    async def _mark_sent(self, notification_id: UUID, provider_id: str, now: datetime) -> None:
        async with self.session_factory() as session:
            notification = await session.scalar(
                select(PendingNotification).where(PendingNotification.id == notification_id)
            )
            if notification is None:
                return
            notification.status = "SENT"
            notification.sent_at = now
            notification.provider_message_id = provider_id
            notification.locked_until = None
            notification.updated_at = now
            session.add(
                AuditEvent(
                    id=uuid4(), tenant_id=notification.tenant_id,
                    action="PENDING_NOTIFICATION_SENT", target_type="pending_notification",
                    target_id=notification.id, correlation_id=notification.correlation_id,
                    event_metadata={"window_index": notification.window_index, "attempts": notification.attempts},
                    created_at=now, updated_at=now,
                )
            )
            await session.commit()

    async def _fail(
        self,
        notification_id: UUID,
        code: str,
        now: datetime,
        retry_after_seconds: int | None = None,
    ) -> None:
        async with self.session_factory() as session:
            notification = await session.scalar(
                select(PendingNotification).where(PendingNotification.id == notification_id)
            )
            if notification is None:
                return
            notification.status = "FAILED"
            notification.failure_code = code[:80]
            notification.locked_until = None
            retry_after = retry_after_seconds or min(900, 2 ** min(notification.attempts, 10))
            notification.next_attempt_at = now + timedelta(seconds=retry_after)
            notification.updated_at = now
            session.add(
                AuditEvent(
                    id=uuid4(), tenant_id=notification.tenant_id,
                    action="PENDING_NOTIFICATION_FAILED", target_type="pending_notification",
                    target_id=notification.id, correlation_id=notification.correlation_id,
                    event_metadata={"failure_code": code[:80], "attempts": notification.attempts},
                    created_at=now, updated_at=now,
                )
            )
            await session.commit()

    async def _cancel(self, notification_id: UUID, now: datetime) -> None:
        async with self.session_factory() as session:
            await session.execute(
                update(PendingNotification)
                .where(PendingNotification.id == notification_id)
                .values(status="CANCELLED", locked_until=None, updated_at=now)
            )
            await session.commit()
