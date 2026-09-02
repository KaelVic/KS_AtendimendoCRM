"""Persist grouped inbound message turns.

Revision ID: 0004_message_turns
Revises: 0003_audit_events
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004_message_turns"
down_revision: Union[str, Sequence[str], None] = "0003_audit_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message_turns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("silence_deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="OPEN"),
        sa.Column("processing_token", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "conversation_id", "window_started_at", name="uq_turn_window"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_turn_tenant_id"),
    )
    op.create_index("ix_turns_due", "message_turns", ["status", "silence_deadline_at"])
    op.create_index("ix_turns_tenant_conversation", "message_turns", ["tenant_id", "conversation_id", "created_at"])
    op.add_column("messages", sa.Column("turn_id", postgresql.UUID(as_uuid=True)))
    op.create_foreign_key("fk_messages_turn", "messages", "message_turns", ["tenant_id", "turn_id"], ["tenant_id", "id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_messages_turn", "messages", type_="foreignkey")
    op.drop_column("messages", "turn_id")
    op.drop_index("ix_turns_tenant_conversation", table_name="message_turns")
    op.drop_index("ix_turns_due", table_name="message_turns")
    op.drop_table("message_turns")
