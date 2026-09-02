"""Persist shard routing, exclusive session ownership and fencing epochs."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0014_channel_router"
down_revision: Union[str, Sequence[str], None] = "0013_outreach_approval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "gateway_shards",
        sa.Column("gateway_id", uuid, nullable=False),
        sa.Column("tenant_id", uuid, nullable=False),
        sa.Column("engine", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="DISABLED"),
        sa.Column("owner_epoch", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("engine_version", sa.String(64), nullable=False, server_default="v0.23.3"),
        sa.Column("last_health_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("health_message", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("gateway_id"),
        sa.UniqueConstraint("tenant_id", "gateway_id", name="uq_gateway_shards_tenant_gateway"),
        sa.CheckConstraint(
            "status IN ('HEALTHY', 'DEGRADED', 'UNAVAILABLE', 'DRAINING', 'DISABLED')",
            name="ck_gateway_shards_status",
        ),
        sa.CheckConstraint("owner_epoch >= 0", name="ck_gateway_shards_owner_epoch_nonnegative"),
        sa.CheckConstraint("version > 0", name="ck_gateway_shards_version_positive"),
    )
    op.create_index("ix_gateway_shards_tenant_status", "gateway_shards", ["tenant_id", "status"])

    # Migrate the original channel_sessions table without discarding its rows.
    op.add_column("channel_sessions", sa.Column("gateway_id", uuid, nullable=True))
    op.add_column("channel_sessions", sa.Column("owner_epoch", sa.BigInteger(), nullable=True))
    op.add_column("channel_sessions", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("channel_sessions", sa.Column("engine_version", sa.String(64), nullable=True))
    op.alter_column("channel_sessions", "provider", new_column_name="engine")
    op.alter_column("channel_sessions", "provider_session_id", new_column_name="external_session_id")
    op.execute("UPDATE channel_sessions SET owner_epoch = 0, engine_version = version")
    op.alter_column(
        "channel_sessions",
        "version",
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="1",
        server_default="1",
    )
    op.execute(
        """
        INSERT INTO gateway_shards (
            gateway_id, tenant_id, engine, status, owner_epoch, version,
            engine_version
        )
        SELECT DISTINCT
            md5('legacy-openwa-gateway:' || tenant_id::text)::uuid,
            tenant_id,
            engine,
            'DISABLED',
            0,
            1,
            COALESCE(engine_version, 'v0.23.3')
        FROM channel_sessions
        ON CONFLICT (gateway_id) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE channel_sessions
        SET gateway_id = md5('legacy-openwa-gateway:' || tenant_id::text)::uuid,
            owner_epoch = COALESCE(owner_epoch, 0),
            engine_version = COALESCE(engine_version, 'v0.23.3')
        """
    )
    op.alter_column("channel_sessions", "gateway_id", nullable=False)
    op.alter_column("channel_sessions", "owner_epoch", nullable=False, server_default="0")
    op.alter_column("channel_sessions", "engine_version", nullable=False, server_default="v0.23.3")
    op.drop_constraint("uq_channel_session_tenant_provider", "channel_sessions", type_="unique")
    op.create_unique_constraint(
        "uq_channel_session_tenant_external",
        "channel_sessions",
        ["tenant_id", "external_session_id"],
    )
    op.create_unique_constraint(
        "uq_channel_session_tenant_gateway_external",
        "channel_sessions",
        ["tenant_id", "gateway_id", "external_session_id"],
    )
    op.create_foreign_key(
        "fk_channel_sessions_gateway_shard",
        "channel_sessions",
        "gateway_shards",
        ["tenant_id", "gateway_id"],
        ["tenant_id", "gateway_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_channel_sessions_status",
        "channel_sessions",
        "status IN ('CONNECTED', 'DISCONNECTED', 'ASSIGNING', 'MIGRATING', 'UNAVAILABLE', 'DISABLED')",
    )
    op.create_check_constraint(
        "ck_channel_sessions_owner_epoch_nonnegative",
        "channel_sessions",
        "owner_epoch >= 0",
    )
    op.create_check_constraint(
        "ck_channel_sessions_version_positive", "channel_sessions", "version > 0"
    )
    op.create_table(
        "session_assignments",
        sa.Column("id", uuid, nullable=False),
        sa.Column("tenant_id", uuid, nullable=False),
        sa.Column("gateway_id", uuid, nullable=False),
        sa.Column("external_session_id", sa.String(255), nullable=False),
        sa.Column("engine", sa.String(32), nullable=False),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="ACTIVE"),
        sa.Column("owner_epoch", sa.BigInteger(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "gateway_id"],
            ["gateway_shards.tenant_id", "gateway_shards.gateway_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "gateway_id", "external_session_id"],
            [
                "channel_sessions.tenant_id",
                "channel_sessions.gateway_id",
                "channel_sessions.external_session_id",
            ],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'EXPIRED', 'RELEASED', 'MIGRATING', 'FENCED')",
            name="ck_session_assignments_status",
        ),
        sa.CheckConstraint("owner_epoch > 0", name="ck_session_assignments_owner_epoch_positive"),
        sa.CheckConstraint("version > 0", name="ck_session_assignments_version_positive"),
    )
    op.create_index(
        "ix_session_assignments_tenant_session",
        "session_assignments",
        ["tenant_id", "external_session_id"],
    )
    op.create_index(
        "uq_session_assignments_active_owner",
        "session_assignments",
        ["tenant_id", "external_session_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )


def downgrade() -> None:
    op.drop_index("uq_session_assignments_active_owner", table_name="session_assignments")
    op.drop_index("ix_session_assignments_tenant_session", table_name="session_assignments")
    op.drop_table("session_assignments")
    op.drop_constraint("ck_channel_sessions_version_positive", "channel_sessions", type_="check")
    op.drop_constraint("ck_channel_sessions_owner_epoch_nonnegative", "channel_sessions", type_="check")
    op.drop_constraint("ck_channel_sessions_status", "channel_sessions", type_="check")
    op.drop_constraint("fk_channel_sessions_gateway_shard", "channel_sessions", type_="foreignkey")
    op.drop_constraint("uq_channel_session_tenant_gateway_external", "channel_sessions", type_="unique")
    op.drop_constraint("uq_channel_session_tenant_external", "channel_sessions", type_="unique")
    op.drop_index("ix_channel_sessions_tenant_status", table_name="channel_sessions")
    op.create_index("ix_channel_sessions_tenant_status", "channel_sessions", ["tenant_id", "status"])
    op.create_unique_constraint(
        "uq_channel_session_tenant_provider",
        "channel_sessions",
        ["tenant_id", "external_session_id"],
    )
    op.alter_column("channel_sessions", "version", type_=sa.String(64), postgresql_using="engine_version")
    op.alter_column("channel_sessions", "external_session_id", new_column_name="provider_session_id")
    op.alter_column("channel_sessions", "engine", new_column_name="provider")
    op.drop_column("channel_sessions", "engine_version")
    op.drop_column("channel_sessions", "lease_expires_at")
    op.drop_column("channel_sessions", "owner_epoch")
    op.drop_column("channel_sessions", "gateway_id")
    op.drop_index("ix_gateway_shards_tenant_status", table_name="gateway_shards")
    op.drop_table("gateway_shards")
