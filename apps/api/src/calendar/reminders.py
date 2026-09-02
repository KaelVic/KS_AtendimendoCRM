from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from .adapter import TransientCalendarError


@dataclass(frozen=True)
class ReminderMessage:
    meeting_id: UUID
    kind: str
    idempotency_key: str


class ReminderProvider(Protocol):
    async def send(self, message: ReminderMessage) -> str: ...


class FakeReminderProvider:
    def __init__(self, fail_times: int = 0):
        self.fail_times = fail_times
        self.sent: dict[str, str] = {}

    async def send(self, message: ReminderMessage) -> str:
        if message.idempotency_key in self.sent:
            return self.sent[message.idempotency_key]
        if self.fail_times:
            self.fail_times -= 1
            raise TransientCalendarError("falha transitória de lembrete")
        provider_id = str(uuid4())
        self.sent[message.idempotency_key] = provider_id
        return provider_id


async def send_reminder_with_retry(provider: ReminderProvider, message: ReminderMessage) -> str:
    for attempt in range(2):
        try:
            return await provider.send(message)
        except TransientCalendarError:
            if attempt == 1:
                raise
    raise AssertionError("unreachable")
