from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

PartKind = Literal["TEXT", "TRANSCRIPT", "IMAGE_DESCRIPTION"]


class MultimodalPart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: PartKind
    content: str = Field(min_length=1, max_length=12_000)
    occurred_at: str | None = Field(default=None, max_length=64)


class LLMRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    conversation_id: UUID
    control_state: Literal["BOT_ACTIVE", "HUMAN_REQUESTED", "HUMAN_ACTIVE", "BOT_RESUMING", "CLOSED"]
    policy_version: str = Field(min_length=1, max_length=64)
    current_summary: str = Field(default="", max_length=12_000)
    parts: list[MultimodalPart] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def reject_empty_context(self) -> "LLMRequest":
        if not self.current_summary.strip() and not any(part.content.strip() for part in self.parts):
            raise ValueError("contexto mínimo ausente")
        return self


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    arguments: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggested_messages: list[str] = Field(default_factory=list, max_length=3)
    intent: str = Field(min_length=1, max_length=120)
    confidence: float = Field(ge=0, le=1)
    updated_summary: str = Field(max_length=12_000)
    crm_fields: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    tool_requests: list[ToolRequest] = Field(default_factory=list, max_length=10)
    escalation_reason: str | None = Field(default=None, max_length=500)


class GenerationResult(BaseModel):
    response: LLMResponse
    pending: bool = False
    used_fallback: bool = False
    repair_attempted: bool = False
