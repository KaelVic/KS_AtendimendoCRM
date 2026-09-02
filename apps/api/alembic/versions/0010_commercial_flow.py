"""Persist explicit acceptance, contract and payment state."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0010_commercial_flow"
down_revision: Union[str, Sequence[str], None] = "0009_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "commercial_orders",
        sa.Column("id", uuid, nullable=False),
        sa.Column("tenant_id", uuid, nullable=False),
        sa.Column("conversation_id", uuid, nullable=False),
        sa.Column("proposal_id", uuid, nullable=False),
        sa.Column("acceptance_idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("expected_amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("catalog_version", sa.String(length=64), nullable=False),
        sa.Column("contract_template_version", sa.String(length=64), nullable=True),
        sa.Column("payment_link_config_version", sa.String(length=64), nullable=True),
        sa.Column("payment_link", sa.String(length=2048), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("contract_ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_link_ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("onboarding_released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["proposals.tenant_id", "proposals.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "proposal_id", name="uq_commercial_orders_proposal"),
        sa.UniqueConstraint(
            "tenant_id", "acceptance_idempotency_key", name="uq_commercial_orders_acceptance_key"
        ),
        sa.CheckConstraint(
            "status IN ('CONTRACT_PENDING', 'PAYMENT_LINK_PENDING', 'PAYMENT_PENDING', 'PAID', 'ONBOARDING_READY', 'CANCELLED', 'REFUNDED')",
            name="ck_commercial_orders_status",
        ),
        sa.CheckConstraint("expected_amount_cents > 0", name="ck_commercial_orders_amount_positive"),
    )
    op.create_index(
        "ix_commercial_orders_tenant_status", "commercial_orders", ["tenant_id", "status", "created_at"]
    )
    op.create_index(
        "ix_commercial_orders_tenant_conversation",
        "commercial_orders",
        ["tenant_id", "conversation_id", "created_at"],
    )

    op.create_table(
        "payment_events",
        sa.Column("id", uuid, nullable=False),
        sa.Column("tenant_id", uuid, nullable=False),
        sa.Column("commercial_order_id", uuid, nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("external_event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "commercial_order_id"],
            ["commercial_orders.tenant_id", "commercial_orders.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "provider", "external_event_id", name="uq_payment_events_external"
        ),
        sa.CheckConstraint(
            "outcome IN ('RECEIVED', 'PROCESSED', 'DUPLICATE', 'REJECTED_AMOUNT', 'REJECTED_STATE', 'REJECTED_TYPE')",
            name="ck_payment_events_outcome",
        ),
    )
    op.create_index(
        "ix_payment_events_tenant_order", "payment_events", ["tenant_id", "commercial_order_id", "created_at"]
    )
    op.create_index(
        "ix_payment_events_tenant_received", "payment_events", ["tenant_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_payment_events_tenant_received", table_name="payment_events")
    op.drop_index("ix_payment_events_tenant_order", table_name="payment_events")
    op.drop_table("payment_events")
    op.drop_index("ix_commercial_orders_tenant_conversation", table_name="commercial_orders")
    op.drop_index("ix_commercial_orders_tenant_status", table_name="commercial_orders")
    op.drop_table("commercial_orders")
