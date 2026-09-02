from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from src.pending.domain import PendingItemData, PendingNotificationCoordinator, PendingStatus
from src.pending.email import EmailMessage, FakeEmailProvider


UTC = timezone.utc


def pending(created_at: datetime | None = None) -> PendingItemData:
    created = created_at or datetime(2026, 8, 31, 10, 0, tzinfo=UTC)
    return PendingItemData(
        id=uuid4(),
        tenant_id=uuid4(),
        conversation_id=uuid4(),
        kind="HUMAN_REQUESTED",
        created_at=created,
        due_at=created,
    )


def test_immediate_and_two_hour_windows_are_deterministic_after_downtime():
    item = pending()
    coordinator = PendingNotificationCoordinator()

    assert coordinator.due_window(item, item.created_at) == 0
    assert coordinator.due_window(item, item.created_at + timedelta(hours=2)) == 1
    assert coordinator.due_window(item, item.created_at + timedelta(hours=10)) == 5


@pytest.mark.asyncio
async def test_fake_email_is_idempotent_and_does_not_resolve_pending():
    provider = FakeEmailProvider()
    message = EmailMessage(
        to="owner@example.test",
        subject="Pendência aguardando ação",
        body="Acesse o CRM para revisar a pendência.",
        idempotency_key="pending-1:window:0",
    )

    first = await provider.send(message)
    second = await provider.send(message)

    assert first.message_id == second.message_id
    assert len(provider.sent) == 1


@pytest.mark.asyncio
async def test_sent_email_does_not_change_open_status():
    item = pending()
    provider = FakeEmailProvider()
    await provider.send(
        EmailMessage(
            to="owner@example.test",
            subject="Pendência",
            body="Acesse o CRM.",
            idempotency_key=f"pending:{item.id}:window:0",
        )
    )
    assert item.status is PendingStatus.OPEN


@pytest.mark.asyncio
async def test_coordinator_claims_only_one_notification_per_window_with_two_workers():
    item = pending()
    coordinator = PendingNotificationCoordinator()
    first = await coordinator.claim(item, item.created_at)
    second = await coordinator.claim(item, item.created_at)

    assert first is not None
    assert second is None
    assert first.window_index == 0

    next_window = await coordinator.claim(item, item.created_at + timedelta(hours=2))
    assert next_window is not None
    assert next_window.window_index == 1
    assert next_window.idempotency_key != first.idempotency_key


@pytest.mark.asyncio
async def test_fake_provider_retries_transient_failure_without_duplicate_delivery():
    provider = FakeEmailProvider(fail_times=1)
    message = EmailMessage(
        to="owner@example.test",
        subject="Pending item",
        body="Open the CRM.",
        idempotency_key="pending-2:window:0",
    )

    with pytest.raises(TimeoutError):
        await provider.send(message)
    first = await provider.send(message)
    second = await provider.send(message)

    assert first.message_id == second.message_id
    assert len(provider.sent) == 1


@pytest.mark.asyncio
async def test_resolved_pending_has_no_new_window_and_new_activity_can_reopen():
    item = pending()
    coordinator = PendingNotificationCoordinator()

    await coordinator.resolve(item, "owner responded")
    assert item.status is PendingStatus.RESOLVED
    assert await coordinator.claim(item, item.created_at + timedelta(hours=2)) is None

    reopened = coordinator.reopen(item, item.created_at + timedelta(hours=3), "new-activity")
    assert reopened.id != item.id
    assert reopened.status is PendingStatus.OPEN
