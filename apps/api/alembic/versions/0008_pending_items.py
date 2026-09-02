"""Add tenant-scoped human pendencies and idempotent reminder windows."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0008_pending_items"
down_revision: Union[str, Sequence[str], None] = "0007_control_state_machine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "pending_items",
        sa.Column("id", uuid, nullable=False),
        sa.Column("tenant_id", uuid, nullable=False),
        sa.Column("conversation_id", uuid, nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="OPEN"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_user_id", uuid, nullable=True),
        sa.Column("resolution_reason", sa.String(length=500), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["resolved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_pending_items_tenant_idempotency"),
        sa.CheckConstraint("status IN ('OPEN', 'RESOLVED')", name="ck_pending_items_status"),
    )
    op.create_index("ix_pending_items_tenant_status_due", "pending_items", ["tenant_id", "status", "due_at"])
    op.create_index(
        "ix_pending_items_tenant_conversation", "pending_items", ["tenant_id", "conversation_id", "created_at"]
    )

    op.create_table(
        "pending_notifications",
        sa.Column("id", uuid, nullable=False),
        sa.Column("tenant_id", uuid, nullable=False),
        sa.Column("pending_item_id", uuid, nullable=False),
        sa.Column("window_index", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=320), nullable=False),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "pending_item_id"],
            ["pending_items.tenant_id", "pending_items.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "pending_item_id", "window_index", name="uq_pending_notifications_window"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_pending_notifications_tenant_idempotency"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'SENT', 'FAILED', 'CANCELLED')",
            name="ck_pending_notifications_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_pending_notifications_attempts_nonnegative"),
    )
    op.create_index(
        "ix_pending_notifications_due", "pending_notifications",
        ["tenant_id", "status", "next_attempt_at", "locked_until"],
    )
    op.create_index(
        "ix_pending_notifications_pending_window", "pending_notifications",
        ["tenant_id", "pending_item_id", "window_index"],
    )


def downgrade() -> None:
    op.drop_index("ix_pending_notifications_pending_window", table_name="pending_notifications")
    op.drop_index("ix_pending_notifications_due", table_name="pending_notifications")
    op.drop_table("pending_notifications")
    op.drop_index("ix_pending_items_tenant_conversation", table_name="pending_items")
    op.drop_index("ix_pending_items_tenant_status_due", table_name="pending_items")
    op.drop_table("pending_items")
