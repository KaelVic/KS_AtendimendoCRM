"""Persist tenant-scoped calendar reservations and reminders."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0011_calendar_meetings"
down_revision: Union[str, Sequence[str], None] = "0010_commercial_flow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "meetings",
        sa.Column("id", uuid, nullable=False),
        sa.Column("tenant_id", uuid, nullable=False),
        sa.Column("conversation_id", uuid, nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("calendar_id", sa.String(length=255), nullable=False),
        sa.Column("external_event_id", sa.String(length=255), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("reminder_kind", sa.String(length=8), nullable=True),
        sa.Column("reminder_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("no_show_marked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_meetings_tenant_id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_meetings_tenant_idempotency"),
        sa.UniqueConstraint("tenant_id", "provider", "external_event_id", name="uq_meetings_external"),
        sa.CheckConstraint(
            "status IN ('SCHEDULED', 'NO_SHOW', 'COMPLETED', 'CANCELLED')",
            name="ck_meetings_status",
        ),
        sa.CheckConstraint("ends_at > starts_at", name="ck_meetings_interval"),
    )
    op.create_index("ix_meetings_tenant_start", "meetings", ["tenant_id", "starts_at"])
    op.create_index("ix_meetings_tenant_status", "meetings", ["tenant_id", "status", "starts_at"])

    op.create_table(
        "meeting_reminders",
        sa.Column("id", uuid, nullable=False),
        sa.Column("tenant_id", uuid, nullable=False),
        sa.Column("meeting_id", uuid, nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("idempotency_key", sa.String(length=320), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "meeting_id"],
            ["meetings.tenant_id", "meetings.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "meeting_id", "kind", name="uq_meeting_reminders_kind"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_meeting_reminders_idempotency"),
        sa.CheckConstraint("kind IN ('2H', '90M')", name="ck_meeting_reminders_kind"),
        sa.CheckConstraint("status IN ('PENDING', 'SENT', 'FAILED', 'CANCELLED')", name="ck_meeting_reminders_status"),
    )
    op.create_index("ix_meeting_reminders_due", "meeting_reminders", ["tenant_id", "status", "due_at"])


def downgrade() -> None:
    op.drop_index("ix_meeting_reminders_due", table_name="meeting_reminders")
    op.drop_table("meeting_reminders")
    op.drop_index("ix_meetings_tenant_status", table_name="meetings")
    op.drop_index("ix_meetings_tenant_start", table_name="meetings")
    op.drop_table("meetings")
