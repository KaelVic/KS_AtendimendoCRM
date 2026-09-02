"""Persist catalog-validated proposal snapshots and line items."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0009_proposals"
down_revision: Union[str, Sequence[str], None] = "0008_pending_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "proposals",
        sa.Column("id", uuid, nullable=False),
        sa.Column("tenant_id", uuid, nullable=False),
        sa.Column("conversation_id", uuid, nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("customer_name", sa.String(length=160), nullable=False),
        sa.Column("need_summary", sa.Text(), nullable=False),
        sa.Column("product_id", sa.String(length=80), nullable=False),
        sa.Column("catalog_version", sa.String(length=64), nullable=False),
        sa.Column("template_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("approval_reason", sa.String(length=500), nullable=True),
        sa.Column("data_hash", sa.String(length=64), nullable=False),
        sa.Column("data_used", postgresql.JSONB(), nullable=False),
        sa.Column("pdf_sha256", sa.String(length=64), nullable=True),
        sa.Column("pdf_storage_key", sa.String(length=512), nullable=True),
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
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_proposals_tenant_idempotency"),
        sa.CheckConstraint(
            "status IN ('RENDERED', 'HUMAN_APPROVAL_REQUIRED')",
            name="ck_proposals_status",
        ),
    )
    op.create_index("ix_proposals_tenant_status_created", "proposals", ["tenant_id", "status", "created_at"])
    op.create_index("ix_proposals_tenant_conversation", "proposals", ["tenant_id", "conversation_id", "created_at"])

    op.create_table(
        "proposal_items",
        sa.Column("id", uuid, nullable=False),
        sa.Column("tenant_id", uuid, nullable=False),
        sa.Column("proposal_id", uuid, nullable=False),
        sa.Column("product_id", sa.String(length=80), nullable=False),
        sa.Column("product_name", sa.String(length=160), nullable=False),
        sa.Column("scope", sa.String(length=1000), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_cents", sa.Integer(), nullable=False),
        sa.Column("line_total_cents", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["proposals.tenant_id", "proposals.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "proposal_id", "product_id", name="uq_proposal_items_product"),
        sa.CheckConstraint("quantity > 0", name="ck_proposal_items_quantity_positive"),
        sa.CheckConstraint("unit_price_cents >= 0", name="ck_proposal_items_price_nonnegative"),
        sa.CheckConstraint("line_total_cents >= 0", name="ck_proposal_items_total_nonnegative"),
    )
    op.create_index("ix_proposal_items_tenant_proposal", "proposal_items", ["tenant_id", "proposal_id"])


def downgrade() -> None:
    op.drop_index("ix_proposal_items_tenant_proposal", table_name="proposal_items")
    op.drop_table("proposal_items")
    op.drop_index("ix_proposals_tenant_conversation", table_name="proposals")
    op.drop_index("ix_proposals_tenant_status_created", table_name="proposals")
    op.drop_table("proposals")
