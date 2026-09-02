from __future__ import annotations

import time
import json
import hashlib

import httpx
from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from ..core.config import get_settings
from ..core.observability import metrics, record_component, record_integration
from ..db.session import check_db_connection
from ..redis.client import check_redis_connection

router = APIRouter(tags=["Health & Status"])
settings = get_settings()


class HealthComponent(BaseModel):
    status: str
    latency_ms: float | None = None
    message: str | None = None
    profile_optional: bool | None = None
    version: str | None = None
    session_id: str | None = None
    owner_configured: bool | None = None
    details: dict[str, object] | None = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str
    components: dict[str, HealthComponent]


async def check_openwa_connection() -> tuple[bool, float, str | None]:
    """Checks only the internal gateway ping; session ownership is separate."""
    started = time.perf_counter()
    url = f"{settings.OPENWA_SERVER_URL}/api/health/ready"
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            response = await client.get(url)
        latency = (time.perf_counter() - started) * 1000.0
        if response.status_code < 500:
            record_integration("openwa", "success", latency)
            return True, round(latency, 2), None
        record_integration("openwa", "error", latency)
        return False, round(latency, 2), f"Status HTTP {response.status_code}"
    except Exception:
        latency = (time.perf_counter() - started) * 1000.0
        record_integration("openwa", "error", latency)
        return False, round(latency, 2), "Gateway OpenWA não iniciado ou fora do profile ativo"


async def check_worker_connection() -> tuple[bool, float, str | None]:
    """Confirms that the worker heartbeat has not expired in Redis."""
    started = time.perf_counter()
    try:
        from ..redis.client import redis_client

        heartbeat = await redis_client.get("worker:heartbeat")
        heartbeat_exists = heartbeat is not None
        latency = (time.perf_counter() - started) * 1000.0
        if heartbeat_exists:
            try:
                heartbeat_text = heartbeat.decode("utf-8") if isinstance(heartbeat, bytes) else heartbeat
                worker_data = json.loads(heartbeat_text) if isinstance(heartbeat_text, str) else {}
                queue_depth = worker_data.get("queue_depth")
                if isinstance(queue_depth, int) and queue_depth >= 0:
                    metrics.set_gauge("ks_queue_depth", queue_depth, labels={"queue": "grouping_due"})
            except (TypeError, ValueError):
                metrics.inc("ks_http_errors_total", labels={"source": "worker_heartbeat"})
            record_integration("worker", "success", latency)
            return True, round(latency, 2), None
        record_integration("worker", "error", latency)
        return False, round(latency, 2), "Heartbeat do worker ausente ou expirado"
    except Exception:
        latency = (time.perf_counter() - started) * 1000.0
        record_integration("worker", "error", latency)
        return False, round(latency, 2), "Não foi possível verificar o heartbeat do worker"


def configured_component(
    component: str, configured: bool, *, simulated: bool = False
) -> dict[str, object]:
    if not configured:
        component_status = "unhealthy"
        message: str | None = "configuração ausente"
    elif simulated:
        component_status = "degraded"
        message = "adapter fake ativo; integração externa não configurada"
    else:
        component_status = "healthy"
        message = None
    record_component(component, component_status != "unhealthy")
    return {"status": component_status, "message": message}


@router.get("/health/live", summary="Liveness Probe")
async def liveness() -> dict[str, str]:
    return {"status": "alive", "service": "ks-api"}


@router.get("/metrics", include_in_schema=False, summary="Internal metrics")
async def metrics_endpoint() -> Response:
    """Prometheus-compatible metrics with bounded, non-sensitive labels."""
    return Response(content=metrics.render(), media_type="text/plain; version=0.0.4")


async def build_health_report(response: Response) -> dict[str, object]:
    db_ok, db_latency, db_error = await check_db_connection()
    redis_ok, redis_latency, redis_error = await check_redis_connection()
    worker_ok, worker_latency, worker_error = await check_worker_connection()
    openwa_ok, openwa_latency, openwa_error = await check_openwa_connection()

    session_status = "healthy" if openwa_ok else (
        "inactive" if not settings.OPENWA_API_KEY else "unhealthy"
    )
    session_metric_label = hashlib.sha256(settings.OPENWA_SESSION_ID.encode()).hexdigest()[:12]
    last_webhook = metrics.get_gauge(
        "ks_openwa_session_last_webhook_timestamp",
        labels={"session_id": session_metric_label},
    )
    last_receipt = metrics.get_gauge(
        "ks_openwa_session_last_receipt_timestamp",
        labels={"session_id": session_metric_label},
    )
    components: dict[str, dict[str, object]] = {
        "postgres": {
            "status": "healthy" if db_ok else "unhealthy",
            "latency_ms": db_latency,
            "message": db_error,
        },
        "redis": {
            "status": "healthy" if redis_ok else "unhealthy",
            "latency_ms": redis_latency,
            "message": redis_error,
        },
        "worker": {
            "status": "healthy" if worker_ok else "unhealthy",
            "latency_ms": worker_latency,
            "message": worker_error,
        },
        "openwa": {
            "status": session_status,
            "latency_ms": openwa_latency,
            "message": openwa_error,
            "profile_optional": True,
            "version": "v0.23.3",
            "session_id": settings.OPENWA_SESSION_ID,
            "owner_configured": bool(settings.OPENWA_API_KEY and settings.OPENWA_SESSION_ID),
        },
        "whatsapp_session": {
            "status": session_status,
            "version": "v0.23.3",
            "session_id": settings.OPENWA_SESSION_ID,
            "owner_configured": bool(settings.OPENWA_API_KEY and settings.OPENWA_SESSION_ID),
            "details": {
                "connection": "CONNECTED" if openwa_ok else "DISCONNECTED",
                "relink_required": False if openwa_ok else bool(settings.OPENWA_API_KEY),
                "last_webhook": last_webhook if last_webhook is not None else "unknown",
                "last_receipt": last_receipt if last_receipt is not None else "unknown",
                "restart_count": "unknown",
                "memory": "unknown",
                "owner_or_shard": "configured" if settings.OPENWA_API_KEY else "unconfigured",
                "shard": settings.OPENWA_SHARD_ID or "unknown",
            },
        },
    }
    components["gemini"] = configured_component(
        "gemini",
        settings.LLM_PROVIDER.lower() != "gemini" or bool(settings.GEMINI_API_KEY),
        simulated=settings.LLM_PROVIDER.lower() != "gemini",
    )
    components["email"] = configured_component(
        "email",
        bool(settings.OWNER_ALERT_EMAIL)
        and (settings.EMAIL_PROVIDER.lower() == "fake" or bool(settings.SMTP_HOST)),
        simulated=settings.EMAIL_PROVIDER.lower() == "fake",
    )
    components["calendar"] = configured_component(
        "calendar",
        settings.CALENDAR_PROVIDER.lower() == "fake"
        or bool(settings.GOOGLE_CALENDAR_CREDENTIALS_JSON),
        simulated=settings.CALENDAR_PROVIDER.lower() == "fake",
    )
    for name, component in components.items():
        latency = component.get("latency_ms")
        if isinstance(latency, (int, float)):
            record_component(name, component["status"] in {"healthy", "degraded"}, latency)

    overall_healthy = db_ok and redis_ok and worker_ok
    if not overall_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "healthy" if overall_healthy else "unhealthy",
        "service": "ks-atendimento-api",
        "version": "0.1.0",
        "environment": settings.ENVIRONMENT,
        "components": components,
    }


@router.get("/health", response_model=HealthResponse, summary="System Health")
async def health_check(response: Response) -> dict[str, object]:
    return await build_health_report(response)


@router.get("/health/ready", response_model=HealthResponse, summary="Readiness Probe")
async def readiness(response: Response) -> dict[str, object]:
    return await build_health_report(response)
