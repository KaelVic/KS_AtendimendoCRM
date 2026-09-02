import time
from typing import Tuple, Optional
import redis.asyncio as aioredis
from ..core.config import get_settings

settings = get_settings()

redis_client = aioredis.from_url(
    settings.get_redis_url(),
    encoding="utf-8",
    decode_responses=True,
)


async def check_redis_connection() -> Tuple[bool, Optional[float], Optional[str]]:
    """Verifica conectividade com Redis retornando (sucesso, latência_ms, erro)."""
    start_time = time.perf_counter()
    try:
        pong = await redis_client.ping()
        latency = (time.perf_counter() - start_time) * 1000.0
        if pong is True:
            return True, round(latency, 2), None
        return False, round(latency, 2), "Resposta ping inesperada"
    except Exception as exc:
        latency = (time.perf_counter() - start_time) * 1000.0
        return False, round(latency, 2), type(exc).__name__
