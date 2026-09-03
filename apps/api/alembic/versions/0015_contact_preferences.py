"""Persist tenant-scoped opt-out and gateway operational checkpoints."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0015_contact_preferences"
down_revision: Union[str, Sequence[str], None] = "0014_channel_router"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_channel_sessions_status", "channel_sessions", type_="check"
    )
    op.create_check_constraint(
        "ck_channel_sessions_status",
        "channel_sessions",
        "status IN ('CONNECTED', 'DISCONNECTED', 'QR_REQUIRED', 'RELINK_REQUIRED', 'ERROR', 'ASSIGNING', 'MIGRATING', 'UNAVAILABLE', 'DISABLED')",
    )
    op.add_column("contacts", sa.Column("opted_out_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("contacts", sa.Column("opt_out_source", sa.String(80), nullable=True))
    op.create_index("ix_contacts_tenant_opted_out", "contacts", ["tenant_id", "opted_out_at"])
    op.add_column("channel_sessions", sa.Column("last_webhook_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("channel_sessions", sa.Column("last_receipt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("channel_sessions", sa.Column("restart_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("channel_sessions", sa.Column("last_failure_code", sa.String(80), nullable=True))


def downgrade() -> None:
    op.drop_column("channel_sessions", "last_failure_code")
    op.drop_column("channel_sessions", "restart_count")
    op.drop_column("channel_sessions", "last_receipt_at")
    op.drop_column("channel_sessions", "last_webhook_at")
    op.drop_index("ix_contacts_tenant_opted_out", table_name="contacts")
    op.drop_column("contacts", "opt_out_source")
    op.drop_column("contacts", "opted_out_at")
    op.drop_constraint(
        "ck_channel_sessions_status", "channel_sessions", type_="check"
    )
    op.create_check_constraint(
        "ck_channel_sessions_status",
        "channel_sessions",
        "status IN ('CONNECTED', 'DISCONNECTED', 'ASSIGNING', 'MIGRATING', 'UNAVAILABLE', 'DISABLED')",
    )
