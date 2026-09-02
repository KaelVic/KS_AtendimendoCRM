"""Persist human-control interval and resumable CRM context.

Revision ID: 0007_control_state_machine
Revises: 0006_media_assets
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0007_control_state_machine"
down_revision: Union[str, Sequence[str], None] = "0006_media_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("context_summary", sa.Text(), nullable=True))
    op.add_column(
        "conversations",
        sa.Column("commercial_state", sa.String(32), nullable=False, server_default="UNKNOWN"),
    )
    op.add_column(
        "conversation_control", sa.Column("human_started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "conversation_control",
        sa.Column("last_human_summary_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversation_control", "last_human_summary_at")
    op.drop_column("conversation_control", "human_started_at")
    op.drop_column("conversations", "commercial_state")
    op.drop_column("conversations", "context_summary")
