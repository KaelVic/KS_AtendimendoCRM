"""Persist tenant-scoped public prospect research awaiting review."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0012_prospect_research"
down_revision: Union[str, Sequence[str], None] = "0011_calendar_meetings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "prospect_researches",
        sa.Column("id", uuid, nullable=False),
        sa.Column("tenant_id", uuid, nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("segment", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "source_fingerprint", name="uq_prospect_research_source"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_prospect_research_idempotency"),
        sa.CheckConstraint(
            "status IN ('PENDING_REVIEW', 'FAILED')",
            name="ck_prospect_research_status",
        ),
    )
    op.create_index(
        "ix_prospect_research_tenant_status",
        "prospect_researches",
        ["tenant_id", "status", "created_at"],
    )
    op.create_index(
        "ix_prospect_research_tenant_source", "prospect_researches", ["tenant_id", "source_url"]
    )


def downgrade() -> None:
    op.drop_index("ix_prospect_research_tenant_source", table_name="prospect_researches")
    op.drop_index("ix_prospect_research_tenant_status", table_name="prospect_researches")
    op.drop_table("prospect_researches")
