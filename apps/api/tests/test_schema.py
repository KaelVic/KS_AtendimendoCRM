import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from src.db.models import Base


def test_core_schema_has_tenant_scope_and_required_indexes():
    expected = {
        "tenants", "users", "contacts", "conversations", "conversation_control", "messages", "audit_events", "message_turns", "channel_sessions", "webhook_events", "outbox_events", "media_assets", "pending_items", "pending_notifications", "proposals", "proposal_items", "commercial_orders", "payment_events", "meetings", "meeting_reminders"
    }
    expected.add("prospect_researches")
    expected.add("outreach_drafts")
    expected.add("gateway_shards")
    expected.add("session_assignments")
    assert set(Base.metadata.tables) == expected

    for name in expected - {"tenants"}:
        assert "tenant_id" in Base.metadata.tables[name].c

    assert "uq_users_tenant_email" in {
        constraint.name for constraint in Base.metadata.tables["users"].constraints
    }
    assert "uq_messages_tenant_idempotency" in {
        constraint.name for constraint in Base.metadata.tables["messages"].constraints
    }
    assert {index.name for index in Base.metadata.tables["messages"].indexes} == {
        "ix_messages_tenant_conversation_created"
    }


def test_core_schema_uses_composite_foreign_keys_for_tenant_isolation():
    for table_name, parent in (
        ("conversations", "contacts"),
        ("conversation_control", "conversations"),
        ("messages", "conversations"),
    ):
        table = Base.metadata.tables[table_name]
        composite = [
            fk
            for fk in table.foreign_key_constraints
            if fk.referred_table.name == parent
        ]
        assert composite
    assert {column.name for column in composite[0].columns} >= {"tenant_id"}


def test_media_schema_is_tenant_scoped_and_has_explicit_constraints():
    table = Base.metadata.tables["media_assets"]
    assert "tenant_id" in table.c
    assert "message_id" in table.c
    assert "uq_media_assets_tenant_idempotency" in {
        constraint.name for constraint in table.constraints
    }
    message_fk = [
        fk for fk in table.foreign_key_constraints if fk.referred_table.name == "messages"
    ]
    assert message_fk
    assert {column.name for column in message_fk[0].columns} == {"tenant_id", "message_id"}


def test_pending_schema_has_idempotent_windows_and_explicit_deletion_rules():
    item = Base.metadata.tables["pending_items"]
    notification = Base.metadata.tables["pending_notifications"]
    assert "uq_pending_items_tenant_idempotency" in {c.name for c in item.constraints}
    assert "uq_pending_notifications_window" in {c.name for c in notification.constraints}
    assert "uq_pending_notifications_tenant_idempotency" in {c.name for c in notification.constraints}
    composite = [fk for fk in notification.foreign_key_constraints if fk.referred_table.name == "pending_items"]
    assert composite
    assert {column.name for column in composite[0].columns} == {"tenant_id", "pending_item_id"}


def test_proposal_schema_has_snapshot_versions_idempotency_and_cascade_items():
    proposal = Base.metadata.tables["proposals"]
    item = Base.metadata.tables["proposal_items"]
    assert {"data_hash", "catalog_version", "template_version", "data_used"} <= {
        column.name for column in proposal.columns
    }
    assert "uq_proposals_tenant_idempotency" in {c.name for c in proposal.constraints}
    assert "ck_proposals_status" in {c.name for c in proposal.constraints}
    item_fk = [fk for fk in item.foreign_key_constraints if fk.referred_table.name == "proposals"]
    assert item_fk
    assert {column.name for column in item_fk[0].columns} == {"tenant_id", "proposal_id"}
    assert all(element.ondelete == "CASCADE" for element in item_fk[0].elements)


def test_commercial_schema_has_explicit_states_and_idempotent_payment_events():
    order = Base.metadata.tables["commercial_orders"]
    payment = Base.metadata.tables["payment_events"]
    assert "uq_commercial_orders_proposal" in {c.name for c in order.constraints}
    assert "uq_commercial_orders_acceptance_key" in {c.name for c in order.constraints}
    assert "ck_commercial_orders_status" in {c.name for c in order.constraints}
    assert "uq_payment_events_external" in {c.name for c in payment.constraints}
    assert "ck_payment_events_outcome" in {c.name for c in payment.constraints}
    order_fk = [fk for fk in payment.foreign_key_constraints if fk.referred_table.name == "commercial_orders"]
    assert order_fk
    assert {column.name for column in order_fk[0].columns} == {"tenant_id", "commercial_order_id"}


def test_meeting_schema_has_tenant_scope_interval_and_idempotent_reminders():
    meeting = Base.metadata.tables["meetings"]
    reminder = Base.metadata.tables["meeting_reminders"]
    assert "uq_meetings_tenant_idempotency" in {c.name for c in meeting.constraints}
    assert "ck_meetings_interval" in {c.name for c in meeting.constraints}
    assert "uq_meeting_reminders_kind" in {c.name for c in reminder.constraints}
    assert "uq_meeting_reminders_idempotency" in {c.name for c in reminder.constraints}
    meeting_fk = [fk for fk in reminder.foreign_key_constraints if fk.referred_table.name == "meetings"]
    assert meeting_fk
    assert {column.name for column in meeting_fk[0].columns} == {"tenant_id", "meeting_id"}
@pytest.mark.asyncio
async def test_database_isolation_idempotency_and_optimistic_concurrency():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL nÃ£o configurada; migraÃ§Ã£o real Ã© validada no job de integraÃ§Ã£o")

    engine = create_async_engine(database_url)
    tenant_a, tenant_b = uuid4(), uuid4()
    contact_a, conversation_a, control_a = uuid4(), uuid4(), uuid4()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO tenants (id, name) VALUES (:id, 'Tenant A'), (:other, 'Tenant B')"),
                {"id": tenant_a, "other": tenant_b},
            )
            await connection.execute(
                text("INSERT INTO contacts (id, tenant_id, normalized_phone) VALUES (:id, :tenant, '+5511999999999')"),
                {"id": contact_a, "tenant": tenant_a},
            )
            await connection.execute(
                text("INSERT INTO conversations (id, tenant_id, contact_id, channel) VALUES (:id, :tenant, :contact, 'SIMULATOR')"),
                {"id": conversation_a, "tenant": tenant_a, "contact": contact_a},
            )
            await connection.execute(
                text("INSERT INTO conversation_control (id, tenant_id, conversation_id) VALUES (:id, :tenant, :conversation)"),
                {"id": control_a, "tenant": tenant_a, "conversation": conversation_a},
            )
            await connection.execute(
                text("INSERT INTO messages (id, tenant_id, conversation_id, channel, idempotency_key, direction, message_type) VALUES (:id, :tenant, :conversation, 'SIMULATOR', 'idem-1', 'INBOUND', 'TEXT')"),
                {"id": uuid4(), "tenant": tenant_a, "conversation": conversation_a},
            )

            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text("INSERT INTO messages (id, tenant_id, conversation_id, channel, idempotency_key, direction, message_type) VALUES (:id, :tenant, :conversation, 'SIMULATOR', 'idem-1', 'INBOUND', 'TEXT')"),
                        {"id": uuid4(), "tenant": tenant_a, "conversation": conversation_a},
                    )

            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text("INSERT INTO conversations (id, tenant_id, contact_id, channel) VALUES (:id, :tenant, :contact, 'SIMULATOR')"),
                        {"id": uuid4(), "tenant": tenant_b, "contact": contact_a},
                    )

            first = await connection.execute(
                text("UPDATE conversation_control SET version = version + 1 WHERE id = :id AND tenant_id = :tenant AND version = 1"),
                {"id": control_a, "tenant": tenant_a},
            )
            second = await connection.execute(
                text("UPDATE conversation_control SET version = version + 1 WHERE id = :id AND tenant_id = :tenant AND version = 1"),
                {"id": control_a, "tenant": tenant_a},
            )
            assert first.rowcount == 1
            assert second.rowcount == 0
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM tenants WHERE id IN (:a, :b)"), {"a": tenant_a, "b": tenant_b})
        await engine.dispose()
