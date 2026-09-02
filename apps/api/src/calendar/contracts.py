from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MeetingCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    starts_at: datetime
    idempotency_key: str = Field(min_length=1, max_length=255)

    @field_validator("starts_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("starts_at deve conter fuso horário")
        return value


class MeetingResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    starts_at: datetime
    ends_at: datetime
    timezone: str
    status: str
    reminder_kind: str | None
    reminder_due_at: datetime | None
    rematch_allowed: bool = False
    duplicate: bool = False


class AvailabilityResponse(BaseModel):
    timezone: str
    slots: list[datetime]


class NoShowResponse(BaseModel):
    meeting_id: UUID
    status: str
    rematch_allowed: bool
