from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=255)
    source_url: HttpUrl
    segment: Literal["ESTHETIC_CLINIC"] = "ESTHETIC_CLINIC"


class BusinessContact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=64)
    source_url: HttpUrl | None = None


class DigitalPresence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    website: bool = False
    instagram: bool = False
    facebook: bool = False
    google_business: bool = False
    other_urls: list[HttpUrl] = Field(default_factory=list, max_length=10)


class VerifiableFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=1, max_length=500)
    evidence_url: HttpUrl


class ProspectResearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str | None = Field(default=None, max_length=160)
    business_contact: BusinessContact = Field(default_factory=BusinessContact)
    evidence_urls: list[HttpUrl] = Field(default_factory=list, max_length=20)
    fetched_at: datetime
    digital_presence: DigitalPresence = Field(default_factory=DigitalPresence)
    findings: list[VerifiableFinding] = Field(default_factory=list, max_length=3)


class ResearchResponse(ProspectResearchResult):
    id: UUID
    tenant_id: UUID
    source_url: HttpUrl
    status: Literal["PENDING_REVIEW", "FAILED"]
    duplicate: bool = False
    failure_code: str | None = None
