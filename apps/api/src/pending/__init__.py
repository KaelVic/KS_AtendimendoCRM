"""Pendências de operação e alertas auditáveis."""

from .domain import (
    PendingItemData,
    PendingNotificationCoordinator,
    PendingStatus,
    window_index,
)
from .email import EmailMessage, EmailProvider, FakeEmailProvider

__all__ = [
    "EmailMessage",
    "EmailProvider",
    "FakeEmailProvider",
    "PendingItemData",
    "PendingNotificationCoordinator",
    "PendingStatus",
    "window_index",
]
