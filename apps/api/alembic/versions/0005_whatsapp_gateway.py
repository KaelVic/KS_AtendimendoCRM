"""Persist gateway sessions, inbound webhooks and outbound outbox."""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005_whatsapp_gateway"
down_revision: Union[str, Sequence[str], None] = "0004_message_turns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False, server_default="OPENWA"),
        sa.Column("provider_session_id", sa.String(255), nullable=False),
        sa.Column("owner_ref", sa.String(255)),
        sa.Column("status", sa.String(32), nullable=False, server_default="DISCONNECTED"),
        sa.Column("version", sa.String(64), nullable=False, server_default="v0.23.3"),
        sa.Column("metadata_json", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "provider_session_id", name="uq_channel_session_tenant_provider"),
    )
    op.create_index("ix_channel_sessions_tenant_status", "channel_sessions", ["tenant_id", "status"])
    op.create_table(
        "webhook_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_event_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "provider_event_id", name="uq_webhook_event_tenant_provider"),
    )
    op.create_index("ix_webhook_events_tenant_received", "webhook_events", ["tenant_id", "created_at"])
    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_outbox_tenant_idempotency"),
    )
    op.create_index("ix_outbox_pending", "outbox_events", ["status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_outbox_pending", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_webhook_events_tenant_received", table_name="webhook_events")
    op.drop_table("webhook_events")
    op.drop_index("ix_channel_sessions_tenant_status", table_name="channel_sessions")
    op.drop_table("channel_sessions")
