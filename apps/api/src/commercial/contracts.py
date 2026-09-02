from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AcceptanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=255)


class CommercialOrderResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    proposal_id: UUID
    conversation_id: UUID
    status: str
    expected_amount_cents: int
    currency: str
    catalog_version: str
    contract_template_version: str | None
    payment_link_config_version: str | None
    payment_link: str | None
    accepted_at: datetime
    paid_at: datetime | None
    onboarding_released_at: datetime | None
    duplicate: bool = False


class PaymentWebhookPayload(BaseModel):
    """Only provider fields needed for a safe state transition are accepted."""

    model_config = ConfigDict(extra="forbid")

    external_event_id: str = Field(min_length=1, max_length=255)
    payment_reference: UUID
    event_type: str = Field(pattern="^(PAYMENT_CONFIRMED|PAYMENT_FAILED)$")
    amount_cents: int = Field(gt=0, le=100_000_000)
    currency: str = Field(pattern="^[A-Z]{3}$")


class PaymentWebhookResponse(BaseModel):
    event_id: UUID
    commercial_order_id: UUID
    status: str
    duplicate: bool = False
