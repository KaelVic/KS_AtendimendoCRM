from typing import Optional, Dict, Any
from datetime import datetime, timezone
from uuid import UUID
from pydantic import BaseModel, Field
from .enums import MessageDirection, MessageType


class StandardErrorEnvelope(BaseModel):
    error_code: str
    message: str
    correlation_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class InboundMessagePayload(BaseModel):
    tenant_id: UUID
    conversation_id: UUID
    external_message_id: str
    direction: MessageDirection = MessageDirection.INBOUND
    message_type: MessageType = MessageType.TEXT
    content: str
    sender_phone: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
