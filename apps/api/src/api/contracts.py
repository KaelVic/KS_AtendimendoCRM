from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    correlation_id: str | None = None
    details: dict | None = None
    timestamp: datetime


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    token: str = Field(min_length=1, max_length=4096)


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_id: UUID
    email: str
    role: str = "OWNER"


class OwnerIdentity(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    email: str
    role: str


class SimulatedMessageRequest(BaseModel):
    tenant_id: UUID
    conversation_id: UUID | None = None
    contact_id: UUID | None = None
    external_message_id: str | None = Field(default=None, min_length=1, max_length=255)
    idempotency_key: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=4000)
    channel: str = Field(default="SIMULATOR", min_length=1, max_length=32)
    message_type: str = Field(default="TEXT", min_length=1, max_length=32)
    sender_phone: str | None = Field(default=None, max_length=32)


class SimulatedMessageResponse(BaseModel):
    message_id: UUID
    tenant_id: UUID
    conversation_id: UUID
    contact_id: UUID
    idempotency_key: str
    duplicate: bool = False
    created_at: datetime


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    tenant_id: UUID
    channel: str
    idempotency_key: str
    direction: str
    message_type: str
    content: str | None
    created_at: datetime


class PaginatedMessages(BaseModel):
    items: list[MessageResponse]
    limit: int
    offset: int
    has_more: bool


class ConversationSummary(BaseModel):
    id: UUID
    tenant_id: UUID
    contact_id: UUID
    channel: str
    status: str
    control_state: str
    control_version: int
    updated_at: datetime


class PaginatedConversations(BaseModel):
    items: list[ConversationSummary]
    limit: int
    offset: int
    has_more: bool


class PendingItemCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    conversation_id: UUID
    kind: str = Field(
        pattern="^(HUMAN_REQUESTED|SPECIAL_COMMERCIAL_RESPONSE|ACCEPTANCE|CONTRACT|PAYMENT|CUSTOM)$",
    )
    idempotency_key: str = Field(min_length=1, max_length=255)
    due_at: datetime | None = None


class PendingNotificationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    window_index: int
    attempts: int
    sent_at: datetime | None
    next_attempt_at: datetime | None


class PendingItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    kind: str
    status: str
    due_at: datetime
    created_at: datetime
    resolved_at: datetime | None
    last_notification: PendingNotificationSummary | None = None


class PaginatedPendingItems(BaseModel):
    items: list[PendingItemResponse]
    limit: int
    offset: int
    has_more: bool


class PendingResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


class SendMessageRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=4000)
    message_type: str = Field(default="TEXT", min_length=1, max_length=32)


class ControlActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(pattern="^(ASSUME|RETURN|REQUEST_ASSIST)$")
    expected_version: int | None = Field(default=None, ge=1)
    reason: str = Field(default="ação do proprietário", min_length=1, max_length=500)


class ControlResponse(BaseModel):
    conversation_id: UUID
    tenant_id: UUID
    state: str
    version: int
    previous_state: str | None = None
    event_id: UUID | None = None


class AssistedDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=4_000)
    facts_hash: str = Field(pattern="^[0-9a-f]{64}$")
    policy_version: str = Field(min_length=1, max_length=64)


class AssistedResponseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    human_content: str | None = Field(default=None, min_length=1, max_length=4_000)
    approved_draft: AssistedDraftRequest | None = None
    tone: str = Field(default="natural", min_length=1, max_length=32)

    @model_validator(mode="after")
    def require_one_human_decision(self) -> "AssistedResponseRequest":
        if bool(self.human_content) == (self.approved_draft is not None):
            raise ValueError("forneça conteúdo ou aprovação humana")
        return self


class AssistedResponseResponse(BaseModel):
    content: str
    facts_hash: str
    state: str
    version: int
