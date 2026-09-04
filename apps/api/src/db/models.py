from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    BigInteger,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    text,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Tenant(Timestamped, Base):
    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")


class User(Timestamped, Base):
    __tablename__ = "users"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        Index("ix_users_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="OWNER")
    auth_subject_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Contact(Timestamped, Base):
    __tablename__ = "contacts"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "id", name="uq_contacts_tenant_id"),
        UniqueConstraint("tenant_id", "normalized_phone", name="uq_contacts_tenant_phone"),
        Index("ix_contacts_tenant_updated", "tenant_id", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    normalized_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opt_out_source: Mapped[str | None] = mapped_column(String(80), nullable=True)


class Conversation(Timestamped, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "contact_id"], ["contacts.tenant_id", "contacts.id"], ondelete="RESTRICT"),
        UniqueConstraint("tenant_id", "id", name="uq_conversations_tenant_id"),
        UniqueConstraint("tenant_id", "channel", "external_conversation_id", name="uq_conversations_external"),
        Index("ix_conversations_tenant_updated", "tenant_id", "updated_at"),
        Index("ix_conversations_tenant_contact", "tenant_id", "contact_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    contact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    external_conversation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN")
    context_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    commercial_state: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN")


class ConversationControl(Timestamped, Base):
    __tablename__ = "conversation_control"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"], ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "conversation_id", name="uq_control_conversation"),
        Index("ix_control_tenant_state", "tenant_id", "state"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="BOT_ACTIVE")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    changed_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    human_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_human_summary_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Message(Timestamped, Base):
    __tablename__ = "messages"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"], ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "id", name="uq_messages_tenant_id"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_messages_tenant_idempotency"),
        UniqueConstraint("tenant_id", "channel", "external_message_id", name="uq_messages_external"),
        Index("ix_messages_tenant_conversation_created", "tenant_id", "conversation_id", "created_at"),
        ForeignKeyConstraint(["tenant_id", "turn_id"], ["message_turns.tenant_id", "message_turns.id"], ondelete="SET NULL"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    external_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    message_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    turn_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class MediaAsset(Timestamped, Base):
    """Validated media owned by a message.

    ``storage_key`` is the canonical artifact retained for CRM processing. For
    images, ``provider_storage_key`` is always the minimized derivative; the
    original is never used as a provider input.
    """

    __tablename__ = "media_assets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "message_id"],
            ["messages.tenant_id", "messages.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_media_assets_tenant_idempotency"),
        Index("ix_media_assets_tenant_message", "tenant_id", "message_id", "created_at"),
        Index("ix_media_assets_tenant_state", "tenant_id", "processing_state"),
        CheckConstraint("size_bytes > 0", name="ck_media_assets_size_positive"),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_media_assets_duration_nonnegative"
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    message_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    processing_state: Mapped[str] = mapped_column(String(24), nullable=False, default="RECEIVED")
    declared_mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    detected_mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    original_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    provider_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    provider_mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)


class MessageTurn(Timestamped, Base):
    __tablename__ = "message_turns"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"], ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "conversation_id", "window_started_at", name="uq_turn_window"),
        UniqueConstraint("tenant_id", "id", name="uq_turn_tenant_id"),
        Index("ix_turns_due", "status", "silence_deadline_at"),
        Index("ix_turns_tenant_conversation", "tenant_id", "conversation_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    silence_deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="OPEN")
    processing_token: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AuditEvent(Timestamped, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        Index("ix_audit_events_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_events_tenant_action", "tenant_id", "action"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class GatewayShard(Timestamped, Base):
    __tablename__ = "gateway_shards"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "gateway_id", name="uq_gateway_shards_tenant_gateway"),
        Index("ix_gateway_shards_tenant_status", "tenant_id", "status"),
        CheckConstraint(
            "status IN ('HEALTHY', 'DEGRADED', 'UNAVAILABLE', 'DRAINING', 'DISABLED')",
            name="ck_gateway_shards_status",
        ),
        CheckConstraint("owner_epoch >= 0", name="ck_gateway_shards_owner_epoch_nonnegative"),
        CheckConstraint("version > 0", name="ck_gateway_shards_version_positive"),
    )

    gateway_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    engine: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="DISABLED")
    owner_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    engine_version: Mapped[str] = mapped_column(String(64), nullable=False, default="v0.23.3")
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    health_message: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ChannelSession(Timestamped, Base):
    __tablename__ = "channel_sessions"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "gateway_id"],
            ["gateway_shards.tenant_id", "gateway_shards.gateway_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "external_session_id", name="uq_channel_session_tenant_external"),
        UniqueConstraint(
            "tenant_id", "gateway_id", "external_session_id",
            name="uq_channel_session_tenant_gateway_external",
        ),
        Index("ix_channel_sessions_tenant_status", "tenant_id", "status"),
        CheckConstraint(
            "status IN ('CONNECTED', 'DISCONNECTED', 'QR_REQUIRED', 'RELINK_REQUIRED', 'ERROR', 'ASSIGNING', 'MIGRATING', 'UNAVAILABLE', 'DISABLED')",
            name="ck_channel_sessions_status",
        ),
        CheckConstraint("owner_epoch >= 0", name="ck_channel_sessions_owner_epoch_nonnegative"),
        CheckConstraint("version > 0", name="ck_channel_sessions_version_positive"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    gateway_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    external_session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    engine: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DISCONNECTED")
    owner_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    engine_version: Mapped[str] = mapped_column(String(64), nullable=False, default="v0.23.3")
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    last_webhook_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_receipt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    restart_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)


class SessionAssignment(Timestamped, Base):
    __tablename__ = "session_assignments"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "gateway_id"],
            ["gateway_shards.tenant_id", "gateway_shards.gateway_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "gateway_id", "external_session_id"],
            ["channel_sessions.tenant_id", "channel_sessions.gateway_id", "channel_sessions.external_session_id"],
            ondelete="CASCADE",
        ),
        Index("ix_session_assignments_tenant_session", "tenant_id", "external_session_id"),
        Index(
            "uq_session_assignments_active_owner",
            "tenant_id", "external_session_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'EXPIRED', 'RELEASED', 'MIGRATING', 'FENCED')",
            name="ck_session_assignments_status",
        ),
        CheckConstraint("owner_epoch > 0", name="ck_session_assignments_owner_epoch_positive"),
        CheckConstraint("version > 0", name="ck_session_assignments_version_positive"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    gateway_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    external_session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    engine: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")
    owner_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WebhookEvent(Timestamped, Base):
    __tablename__ = "webhook_events"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "provider_event_id", name="uq_webhook_event_tenant_provider"),
        Index("ix_webhook_events_tenant_received", "tenant_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OutboxEvent(Timestamped, Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_outbox_tenant_idempotency"),
        Index("ix_outbox_pending", "status", "next_attempt_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PendingItem(Timestamped, Base):
    """Human action required before the conversation can safely continue."""

    __tablename__ = "pending_items"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["resolved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        UniqueConstraint("tenant_id", "id", name="uq_pending_items_tenant_id"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_pending_items_tenant_idempotency"),
        Index("ix_pending_items_tenant_status_due", "tenant_id", "status", "due_at"),
        Index("ix_pending_items_tenant_conversation", "tenant_id", "conversation_id", "created_at"),
        CheckConstraint("status IN ('OPEN', 'RESOLVED')", name="ck_pending_items_status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    resolution_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class PendingNotification(Timestamped, Base):
    """One immediate or two-hour reminder window for a pending item."""

    __tablename__ = "pending_notifications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "pending_item_id"],
            ["pending_items.tenant_id", "pending_items.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id", "pending_item_id", "window_index",
            name="uq_pending_notifications_window",
        ),
        UniqueConstraint(
            "tenant_id", "idempotency_key",
            name="uq_pending_notifications_tenant_idempotency",
        ),
        Index(
            "ix_pending_notifications_due",
            "tenant_id", "status", "next_attempt_at", "locked_until",
        ),
        Index(
            "ix_pending_notifications_pending_window",
            "tenant_id", "pending_item_id", "window_index",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'SENT', 'FAILED', 'CANCELLED')",
            name="ck_pending_notifications_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_pending_notifications_attempts_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    pending_item_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    window_index: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(320), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)


class Proposal(Timestamped, Base):
    """Reproducible proposal snapshot generated from an approved catalog."""

    __tablename__ = "proposals"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_proposals_tenant_id"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_proposals_tenant_idempotency"),
        Index("ix_proposals_tenant_status_created", "tenant_id", "status", "created_at"),
        Index("ix_proposals_tenant_conversation", "tenant_id", "conversation_id", "created_at"),
        CheckConstraint(
            "status IN ('RENDERED', 'HUMAN_APPROVAL_REQUIRED')",
            name="ck_proposals_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_name: Mapped[str] = mapped_column(String(160), nullable=False)
    need_summary: Mapped[str] = mapped_column(Text, nullable=False)
    product_id: Mapped[str] = mapped_column(String(80), nullable=False)
    catalog_version: Mapped[str] = mapped_column(String(64), nullable=False)
    template_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    approval_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    data_used: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    pdf_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pdf_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ProposalItem(Timestamped, Base):
    __tablename__ = "proposal_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["proposals.tenant_id", "proposals.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "proposal_id", "product_id", name="uq_proposal_items_product"),
        Index("ix_proposal_items_tenant_proposal", "tenant_id", "proposal_id"),
        CheckConstraint("quantity > 0", name="ck_proposal_items_quantity_positive"),
        CheckConstraint("unit_price_cents >= 0", name="ck_proposal_items_price_nonnegative"),
        CheckConstraint("line_total_cents >= 0", name="ck_proposal_items_total_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    proposal_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    product_id: Mapped[str] = mapped_column(String(80), nullable=False)
    product_name: Mapped[str] = mapped_column(String(160), nullable=False)
    scope: Mapped[str] = mapped_column(String(1_000), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total_cents: Mapped[int] = mapped_column(Integer, nullable=False)


class CommercialOrder(Timestamped, Base):
    """Acceptance snapshot and deterministic contract/payment state."""

    __tablename__ = "commercial_orders"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["proposals.tenant_id", "proposals.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_commercial_orders_tenant_id"),
        UniqueConstraint("tenant_id", "proposal_id", name="uq_commercial_orders_proposal"),
        UniqueConstraint(
            "tenant_id", "acceptance_idempotency_key", name="uq_commercial_orders_acceptance_key"
        ),
        Index("ix_commercial_orders_tenant_status", "tenant_id", "status", "created_at"),
        Index("ix_commercial_orders_tenant_conversation", "tenant_id", "conversation_id", "created_at"),
        CheckConstraint(
            "status IN ('CONTRACT_PENDING', 'PAYMENT_LINK_PENDING', 'PAYMENT_PENDING', 'PAID', 'ONBOARDING_READY', 'CANCELLED', 'REFUNDED')",
            name="ck_commercial_orders_status",
        ),
        CheckConstraint("expected_amount_cents > 0", name="ck_commercial_orders_amount_positive"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    proposal_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    acceptance_idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BRL")
    catalog_version: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_template_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payment_link_config_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payment_link: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    contract_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_link_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    onboarding_released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class PaymentEvent(Timestamped, Base):
    """Sanitized, signed provider event; raw webhook bodies are not persisted."""

    __tablename__ = "payment_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "commercial_order_id"],
            ["commercial_orders.tenant_id", "commercial_orders.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id", "provider", "external_event_id", name="uq_payment_events_external"
        ),
        Index("ix_payment_events_tenant_order", "tenant_id", "commercial_order_id", "created_at"),
        Index("ix_payment_events_tenant_received", "tenant_id", "created_at"),
        CheckConstraint(
            "outcome IN ('RECEIVED', 'PROCESSED', 'DUPLICATE', 'REJECTED_AMOUNT', 'REJECTED_STATE', 'REJECTED_TYPE')",
            name="ck_payment_events_outcome",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    commercial_order_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False, default="RECEIVED")
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Meeting(Timestamped, Base):
    """CRM meeting reservation; the KS calendar is the only write target."""

    __tablename__ = "meetings"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_meetings_tenant_id"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_meetings_tenant_idempotency"),
        UniqueConstraint("tenant_id", "provider", "external_event_id", name="uq_meetings_external"),
        Index("ix_meetings_tenant_start", "tenant_id", "starts_at"),
        Index("ix_meetings_tenant_status", "tenant_id", "status", "starts_at"),
        CheckConstraint(
            "status IN ('SCHEDULED', 'NO_SHOW', 'COMPLETED', 'CANCELLED')",
            name="ck_meetings_status",
        ),
        CheckConstraint("ends_at > starts_at", name="ck_meetings_interval"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    calendar_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="America/Sao_Paulo")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="SCHEDULED")
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    reminder_kind: Mapped[str | None] = mapped_column(String(8), nullable=True)
    reminder_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    no_show_marked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class MeetingReminder(Timestamped, Base):
    __tablename__ = "meeting_reminders"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "meeting_id"],
            ["meetings.tenant_id", "meetings.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "meeting_id", "kind", name="uq_meeting_reminders_kind"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_meeting_reminders_idempotency"),
        Index("ix_meeting_reminders_due", "tenant_id", "status", "due_at"),
        CheckConstraint("kind IN ('2H', '90M')", name="ck_meeting_reminders_kind"),
        CheckConstraint("status IN ('PENDING', 'SENT', 'FAILED', 'CANCELLED')", name="ck_meeting_reminders_status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    meeting_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(320), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ProspectResearch(Timestamped, Base):
    """Tenant-scoped public-source research awaiting human review.

    Only normalized, structured findings are retained here. The original page
    is not trusted and is deliberately not stored as an executable prompt.
    """

    __tablename__ = "prospect_researches"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "id", name="uq_prospect_researches_tenant_id"),
        UniqueConstraint("tenant_id", "source_fingerprint", name="uq_prospect_research_source"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_prospect_research_idempotency"),
        Index("ix_prospect_research_tenant_status", "tenant_id", "status", "created_at"),
        Index("ix_prospect_research_tenant_source", "tenant_id", "source_url"),
        CheckConstraint(
            "status IN ('PENDING_REVIEW', 'FAILED')",
            name="ck_prospect_research_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    segment: Mapped[str] = mapped_column(String(64), nullable=False, default="ESTHETIC_CLINIC")
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING_REVIEW")
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class OutreachDraft(Timestamped, Base):
    """Human-reviewable first-contact draft derived from public research."""

    __tablename__ = "outreach_drafts"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "research_id"],
            ["prospect_researches.tenant_id", "prospect_researches.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        UniqueConstraint("tenant_id", "research_id", name="uq_outreach_draft_research"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_outreach_draft_idempotency"),
        Index("ix_outreach_drafts_tenant_status", "tenant_id", "status", "created_at"),
        Index("ix_outreach_drafts_tenant_recipient", "tenant_id", "recipient_ref"),
        CheckConstraint(
            "status IN ('PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'EXPIRED', 'SENDING', 'SENT', 'PAUSED')",
            name="ck_outreach_draft_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    research_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    findings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    recipient_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    draft_text: Mapped[str] = mapped_column(Text, nullable=False)
    approach_reason: Mapped[str] = mapped_column(String(500), nullable=False)
    research_data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    message_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING_APPROVAL")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    approved_research_data_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_message_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_recipient_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    send_idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pause_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
