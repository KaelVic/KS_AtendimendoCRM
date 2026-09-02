from enum import Enum


class ConversationControlState(str, Enum):
    """Estados explícitos de controle da conversa conforme AGENTS.md §7."""
    BOT_ACTIVE = "BOT_ACTIVE"
    HUMAN_REQUESTED = "HUMAN_REQUESTED"
    HUMAN_ACTIVE = "HUMAN_ACTIVE"
    AI_ASSISTED_PENDING = "AI_ASSISTED_PENDING"
    BOT_RESUMING = "BOT_RESUMING"
    CLOSED = "CLOSED"


class MessageDirection(str, Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class MessageType(str, Enum):
    TEXT = "TEXT"
    AUDIO = "AUDIO"
    IMAGE = "IMAGE"
    DOCUMENT = "DOCUMENT"
    SYSTEM = "SYSTEM"


class OutboxStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
