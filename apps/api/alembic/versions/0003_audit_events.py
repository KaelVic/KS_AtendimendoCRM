"""Add tenant-scoped audit events.

Revision ID: 0003_audit_events
Revises: 0002_core_crm
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003_audit_events"
down_revision: Union[str, Sequence[str], None] = "0002_core_crm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(80), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True)),
        sa.Column("correlation_id", sa.String(36), nullable=False),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_audit_events_tenant_created", "audit_events", ["tenant_id", "created_at"])
    op.create_index("ix_audit_events_tenant_action", "audit_events", ["tenant_id", "action"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_tenant_action", table_name="audit_events")
    op.drop_index("ix_audit_events_tenant_created", table_name="audit_events")
    op.drop_table("audit_events")
