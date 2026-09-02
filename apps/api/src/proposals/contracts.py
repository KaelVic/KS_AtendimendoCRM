from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProposalLineDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(pattern="^[a-z0-9-]{1,80}$")
    quantity: int = Field(ge=1, le=20)


class ProposalDraft(BaseModel):
    """Structured model output; money and delivery are checked server-side."""

    model_config = ConfigDict(extra="forbid")

    customer: str = Field(min_length=1, max_length=160)
    need: str = Field(min_length=1, max_length=4_000)
    product_id: str = Field(pattern="^[a-z0-9-]{1,80}$")
    items: list[ProposalLineDraft] = Field(min_length=1, max_length=10)
    price_cents: int = Field(ge=0, le=100_000_000)
    delivery_days: int = Field(ge=0, le=365)
    revisions: int = Field(ge=0, le=20)
    scope: str = Field(min_length=1, max_length=1_000)
    observations: list[str] = Field(default_factory=list, max_length=20)
    discount_cents: int = Field(default=0, ge=0, le=100_000_000)
    additional_scope: str | None = Field(default=None, max_length=1_000)


class ProposalCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    conversation_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=255)
    draft: ProposalDraft


class ProposalResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    status: str
    approval_reasons: list[str]
    catalog_version: str
    template_version: str
    data_hash: str
    pdf_sha256: str | None
    pdf_storage_key: str | None
    duplicate: bool = False
