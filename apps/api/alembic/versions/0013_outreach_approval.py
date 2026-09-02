"""Persist human approval and idempotent cold-outreach drafts."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0013_outreach_approval"
down_revision: Union[str, Sequence[str], None] = "0012_prospect_research"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "outreach_drafts",
        sa.Column("id", uuid, nullable=False),
        sa.Column("tenant_id", uuid, nullable=False),
        sa.Column("research_id", uuid, nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("company_name", sa.String(length=160), nullable=True),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("source_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("findings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("recipient_ref", sa.String(length=255), nullable=False),
        sa.Column("draft_text", sa.Text(), nullable=False),
        sa.Column("approach_reason", sa.String(length=500), nullable=False),
        sa.Column("research_data_hash", sa.String(length=64), nullable=False),
        sa.Column("message_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_user_id", uuid, nullable=True),
        sa.Column("approved_research_data_hash", sa.String(length=64), nullable=True),
        sa.Column("approved_message_hash", sa.String(length=64), nullable=True),
        sa.Column("approved_recipient_ref", sa.String(length=255), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.String(length=500), nullable=True),
        sa.Column("opted_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("send_idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("pause_reason", sa.String(length=120), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "research_id"],
            ["prospect_researches.tenant_id", "prospect_researches.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "research_id", name="uq_outreach_draft_research"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_outreach_draft_idempotency"),
        sa.CheckConstraint(
            "status IN ('PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'EXPIRED', 'SENDING', 'SENT', 'PAUSED')",
            name="ck_outreach_draft_status",
        ),
    )
    op.create_index(
        "ix_outreach_drafts_tenant_status",
        "outreach_drafts",
        ["tenant_id", "status", "created_at"],
    )
    op.create_index(
        "ix_outreach_drafts_tenant_recipient", "outreach_drafts", ["tenant_id", "recipient_ref"]
    )


def downgrade() -> None:
    op.drop_index("ix_outreach_drafts_tenant_recipient", table_name="outreach_drafts")
    op.drop_index("ix_outreach_drafts_tenant_status", table_name="outreach_drafts")
    op.drop_table("outreach_drafts")
