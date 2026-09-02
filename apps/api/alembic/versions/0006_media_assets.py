"""Persist validated media and its processing artifacts.

Revision ID: 0006_media_assets
Revises: 0005_whatsapp_gateway
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0006_media_assets"
down_revision: Union[str, Sequence[str], None] = "0005_whatsapp_gateway"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("processing_state", sa.String(24), nullable=False, server_default="RECEIVED"),
        sa.Column("declared_mime_type", sa.String(120), nullable=False),
        sa.Column("detected_mime_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=True),
        sa.Column("original_storage_key", sa.String(512), nullable=True),
        sa.Column("provider_storage_key", sa.String(512), nullable=True),
        sa.Column("provider_mime_type", sa.String(120), nullable=True),
        sa.Column("transcript", sa.Text, nullable=True),
        sa.Column("failure_code", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "message_id"],
            ["messages.tenant_id", "messages.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_media_assets_tenant_idempotency"),
        sa.CheckConstraint("size_bytes > 0", name="ck_media_assets_size_positive"),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_media_assets_duration_nonnegative"
        ),
    )
    op.create_index(
        "ix_media_assets_tenant_message",
        "media_assets",
        ["tenant_id", "message_id", "created_at"],
    )
    op.create_index("ix_media_assets_tenant_state", "media_assets", ["tenant_id", "processing_state"])


def downgrade() -> None:
    op.drop_index("ix_media_assets_tenant_state", table_name="media_assets")
    op.drop_index("ix_media_assets_tenant_message", table_name="media_assets")
    op.drop_table("media_assets")
