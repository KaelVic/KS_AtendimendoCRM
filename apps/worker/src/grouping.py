"""Redis-backed debounce policy for persisted inbound message turns."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID, uuid4

SILENCE_SECONDS = 7
MAX_WINDOW_SECONDS = 25


class RedisLike(Protocol):
    async def hgetall(self, name: str) -> dict[str, str]: ...
    async def hset(self, name: str, mapping: dict[str, str]) -> int: ...
    async def zadd(self, name: str, mapping: dict[str, float]) -> int: ...
    async def set(self, name: str, value: str, *, nx: bool, ex: int) -> bool | None: ...
    async def delete(self, name: str) -> int: ...
    async def eval(self, script: str, numkeys: int, key: str, token: str) -> int: ...


@dataclass(frozen=True)
class GroupingWindow:
    started_at: datetime
    silence_deadline: datetime
    max_deadline: datetime

    @property
    def due_at(self) -> datetime:
        return min(self.silence_deadline, self.max_deadline)


def utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def next_window(existing: GroupingWindow | None, fragment_at: datetime) -> GroupingWindow:
    fragment_at = utc(fragment_at)
    if existing is None:
        return GroupingWindow(fragment_at, fragment_at + timedelta(seconds=SILENCE_SECONDS), fragment_at + timedelta(seconds=MAX_WINDOW_SECONDS))
    return GroupingWindow(existing.started_at, min(fragment_at + timedelta(seconds=SILENCE_SECONDS), existing.max_deadline), existing.max_deadline)


class RedisDebounceScheduler:
    def __init__(self, redis: RedisLike, key_prefix: str = "ks:grouping"):
        self.redis = redis
        self.prefix = key_prefix

    async def register(self, conversation_id: UUID, fragment_at: datetime) -> GroupingWindow:
        key = f"{self.prefix}:window:{conversation_id}"
        raw = await self.redis.hgetall(key)
        existing = None
        if raw:
            existing = GroupingWindow(datetime.fromisoformat(raw["started_at"]), datetime.fromisoformat(raw["silence_deadline"]), datetime.fromisoformat(raw["max_deadline"]))
        window = next_window(existing, fragment_at)
        await self.redis.hset(key, mapping={"started_at": window.started_at.isoformat(), "silence_deadline": window.silence_deadline.isoformat(), "max_deadline": window.max_deadline.isoformat()})
        await self.redis.zadd(f"{self.prefix}:due", {str(conversation_id): window.due_at.timestamp()})
        return window


class ConversationLock:
    """Short-lived ownership token; the DB transaction remains authoritative."""

    def __init__(self, redis: RedisLike, conversation_id: UUID, ttl_seconds: int = 30, key_prefix: str = "ks:grouping"):
        self.redis = redis
        self.key = f"{key_prefix}:lock:{conversation_id}"
        self.ttl_seconds = ttl_seconds
        self.token = str(uuid4())

    async def acquire(self) -> bool:
        return bool(await self.redis.set(self.key, self.token, nx=True, ex=self.ttl_seconds))

    async def release(self) -> None:
        await self.redis.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
            1,
            self.key,
            self.token,
        )
