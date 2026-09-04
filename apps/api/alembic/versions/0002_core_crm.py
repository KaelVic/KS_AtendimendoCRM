"""Create tenant-scoped CRM core tables.

Revision ID: 0002_core_crm
Revises: 0001_foundation_baseline
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002_core_crm"
down_revision: Union[str, Sequence[str], None] = "0001_foundation_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)
NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_tenants_name_nonempty"),
    )
    op.create_table(
        "users",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="OWNER"),
        sa.Column("auth_subject_ref", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        sa.CheckConstraint("length(trim(email)) > 3", name="ck_users_email_nonempty"),
    )
    op.create_index("ix_users_tenant", "users", ["tenant_id"])
    op.create_table(
        "contacts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("display_name", sa.String(160)),
        sa.Column("normalized_phone", sa.String(32)),
        sa.Column("email", sa.String(320)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_contacts_tenant_id"),
        sa.UniqueConstraint("tenant_id", "normalized_phone", name="uq_contacts_tenant_phone"),
    )
    op.create_index("ix_contacts_tenant_updated", "contacts", ["tenant_id", "updated_at"])
    op.create_table(
        "conversations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("contact_id", UUID, nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("external_conversation_id", sa.String(255)),
        sa.Column("status", sa.String(32), nullable=False, server_default="OPEN"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "contact_id"], ["contacts.tenant_id", "contacts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_conversations_tenant_id"),
        sa.UniqueConstraint("tenant_id", "channel", "external_conversation_id", name="uq_conversations_external"),
    )
    op.create_index("ix_conversations_tenant_updated", "conversations", ["tenant_id", "updated_at"])
    op.create_index("ix_conversations_tenant_contact", "conversations", ["tenant_id", "contact_id"])
    op.create_table(
        "conversation_control",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("state", sa.String(32), nullable=False, server_default="BOT_ACTIVE"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("changed_by_user_id", UUID),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.ForeignKeyConstraint(["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["changed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "conversation_id", name="uq_control_conversation"),
    )
    op.create_index("ix_control_tenant_state", "conversation_control", ["tenant_id", "state"])
    op.create_table(
        "messages",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("external_message_id", sa.String(255)),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("message_type", sa.String(32), nullable=False),
        sa.Column("content", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.ForeignKeyConstraint(["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_messages_tenant_id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_messages_tenant_idempotency"),
        sa.UniqueConstraint("tenant_id", "channel", "external_message_id", name="uq_messages_external"),
    )
    op.create_index("ix_messages_tenant_conversation_created", "messages", ["tenant_id", "conversation_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_messages_tenant_conversation_created", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_control_tenant_state", table_name="conversation_control")
    op.drop_table("conversation_control")
    op.drop_index("ix_conversations_tenant_contact", table_name="conversations")
    op.drop_index("ix_conversations_tenant_updated", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index("ix_contacts_tenant_updated", table_name="contacts")
    op.drop_table("contacts")
    op.drop_index("ix_users_tenant", table_name="users")
    op.drop_table("users")
    op.drop_table("tenants")
