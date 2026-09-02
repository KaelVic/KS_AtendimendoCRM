from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    body: str
    idempotency_key: str


@dataclass(frozen=True)
class EmailSendResult:
    message_id: str


class EmailProvider(Protocol):
    async def send(self, message: EmailMessage) -> EmailSendResult: ...


class FakeEmailProvider:
    """Contract fake: at-least-once calls become one delivered email."""

    def __init__(self, *, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.sent: list[EmailMessage] = []
        self._results: dict[str, EmailSendResult] = {}

    async def send(self, message: EmailMessage) -> EmailSendResult:
        if self.fail_times:
            self.fail_times -= 1
            raise TimeoutError("fake email provider timeout")
        existing = self._results.get(message.idempotency_key)
        if existing:
            return existing
        result = EmailSendResult(message_id=str(uuid4()))
        self._results[message.idempotency_key] = result
        self.sent.append(message)
        return result
