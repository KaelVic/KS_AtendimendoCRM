from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OutreachDraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=255)
    draft_text: str = Field(min_length=1, max_length=4_000)
    approach_reason: str = Field(min_length=1, max_length=500)


class OutreachEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_text: str | None = Field(default=None, min_length=1, max_length=4_000)
    approach_reason: str | None = Field(default=None, min_length=1, max_length=500)
    recipient_ref: str | None = Field(default=None, min_length=8, max_length=32)

    @model_validator(mode="after")
    def require_change(self) -> "OutreachEdit":
        if self.draft_text is None and self.approach_reason is None and self.recipient_ref is None:
            raise ValueError("ao menos um campo deve ser alterado")
        return self


class OutreachApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: Literal[True]


class OutreachReject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


class OutreachSend(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=255)


class OutreachDraftResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    research_id: UUID
    company: str | None
    source_url: str
    evidence_urls: list[str]
    findings: list[dict]
    contact: str
    draft_text: str
    approach_reason: str
    status: Literal[
        "PENDING_APPROVAL", "APPROVED", "REJECTED", "EXPIRED", "SENDING", "SENT", "PAUSED"
    ]
    expires_at: datetime | None
    approved_at: datetime | None
    sent_at: datetime | None
    provider_message_id: str | None
    pause_reason: str | None
    duplicate: bool = False
