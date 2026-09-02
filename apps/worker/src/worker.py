import asyncio
import signal
import sys
import json
import logging
from datetime import datetime, timezone
import redis.asyncio as aioredis
from .config import WorkerSettings
from .pending_jobs import PendingNotificationJob

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ks_worker")

settings = WorkerSettings()


class AsyncWorker:
    def __init__(self, pending_job: PendingNotificationJob | None = None):
        self.running = False
        self.redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        self.pending_job = pending_job or self._build_pending_job()

    @staticmethod
    def _build_pending_job() -> PendingNotificationJob | None:
        """Build the job only in the container where the API package is present."""
        try:
            from api_src.core.config import get_settings  # type: ignore[import-not-found]
            from api_src.db.session import async_session_factory  # type: ignore[import-not-found]
            from api_src.pending.dispatcher import PendingNotificationDispatcher  # type: ignore[import-not-found]
            from api_src.pending.email import FakeEmailProvider  # type: ignore[import-not-found]
        except ImportError:
            return None
        api_settings = get_settings()
        dispatcher = PendingNotificationDispatcher(
            async_session_factory,
            FakeEmailProvider(),
            api_settings.OWNER_ALERT_EMAIL,
        )
        return PendingNotificationJob(dispatcher.dispatch_once)

    async def heartbeat(self):
        """Atualiza a chave de heartbeat no Redis periodicamente."""
        while self.running:
            try:
                payload = json.dumps({
                    "status": "alive",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "environment": settings.ENVIRONMENT,
                    "queue_depth": await self.redis_client.zcard("ks:grouping:due"),
                })
                await self.redis_client.set(
                    "worker:heartbeat",
                    payload,
                    ex=settings.HEARTBEAT_TTL_SECONDS,
                )
                logger.debug("Worker heartbeat atualizado no Redis.")
            except Exception as exc:
                logger.warning(f"Falha ao registrar heartbeat no Redis: {exc}")
            await asyncio.sleep(settings.HEARTBEAT_INTERVAL_SECONDS)

    async def process_queues(self):
        """Loop de consumo de filas com timeout para permitir encerramento limpo."""
        logger.info("Worker pronto para processamento de filas.")
        while self.running:
            # Em Fase 0 mantemos o loop ativo e saudável
            if self.pending_job:
                try:
                    await self.pending_job.run_once()
                except Exception as exc:
                    logger.warning("Falha no job de pendências: %s", type(exc).__name__)
            await asyncio.sleep(settings.PENDING_POLL_INTERVAL_SECONDS)

    async def start(self):
        self.running = True
        logger.info("Iniciando KS Async Worker...")
        try:
            await self.redis_client.ping()
            logger.info("Conectado ao Redis com sucesso.")
        except Exception as exc:
            logger.error(f"Erro ao conectar no Redis: {exc}")

        # Executa heartbeat e processamento em paralelo
        await asyncio.gather(
            self.heartbeat(),
            self.process_queues(),
        )

    async def stop(self):
        logger.info("Encerrando KS Async Worker graciosamente...")
        self.running = False
        try:
            await self.redis_client.delete("worker:heartbeat")
            await self.redis_client.close()
        except Exception:
            pass
        logger.info("KS Async Worker finalizado.")


async def main():
    worker = AsyncWorker()

    def handle_signal():
        asyncio.create_task(worker.stop())

    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, handle_signal)

    try:
        await worker.start()
    except (asyncio.CancelledError, KeyboardInterrupt):
        await worker.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
