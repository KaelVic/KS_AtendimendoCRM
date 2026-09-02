from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from apps.worker.src.grouping import ConversationLock, RedisDebounceScheduler, next_window


BASE = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("offset,expected", [(0, 7), (2, 9), (17.9, 24.9), (18, 25), (20, 25)])
def test_silence_restarts_without_crossing_25_seconds(offset, expected):
    window = next_window(None, BASE)
    window = next_window(window, BASE.replace(second=0) + __import__("datetime").timedelta(seconds=offset))
    assert (window.due_at - BASE).total_seconds() == expected


def test_new_window_after_maximum_is_independent():
    window = next_window(None, BASE)
    assert next_window(window, BASE + __import__("datetime").timedelta(seconds=25)).due_at == BASE + __import__("datetime").timedelta(seconds=25)


class FakeRedis:
    def __init__(self):
        self.hashes = {}
        self.scores = {}

    async def hgetall(self, name):
        return self.hashes.get(name, {})

    async def hset(self, name, mapping):
        self.hashes[name] = mapping
        return 1

    async def zadd(self, name, mapping):
        self.scores.update(mapping)
        return 1

    async def set(self, name, value, *, nx, ex):
        if nx and name in self.hashes:
            return False
        self.hashes[name] = {"value": value, "ttl": str(ex)}
        return True

    async def delete(self, name):
        self.hashes.pop(name, None)
        return 1

    async def eval(self, script, numkeys, key, token):
        current = self.hashes.get(key, {}).get("value")
        if current == token:
            return await self.delete(key)
        return 0


@pytest.mark.asyncio
async def test_restart_reuses_persisted_redis_window_and_timer():
    redis = FakeRedis()
    conversation = uuid4()
    first = await RedisDebounceScheduler(redis).register(conversation, BASE)
    second = await RedisDebounceScheduler(redis).register(conversation, BASE + __import__("datetime").timedelta(seconds=2))
    assert second.started_at == first.started_at
    assert second.due_at == BASE + __import__("datetime").timedelta(seconds=9)
    assert str(conversation) in redis.scores


@pytest.mark.asyncio
async def test_only_one_worker_owns_conversation_lock():
    redis = FakeRedis()
    first = ConversationLock(redis, uuid4())
    second = ConversationLock(redis, UUID(first.key.rsplit(":", 1)[-1]))
    assert await first.acquire() is True
    assert await second.acquire() is False
    await first.release()
    assert await second.acquire() is True
