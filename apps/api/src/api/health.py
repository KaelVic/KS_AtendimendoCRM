from __future__ import annotations

import time
import json
import hashlib
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from ..core.config import get_settings
from ..core.observability import metrics, record_component, record_integration
from ..db.session import check_db_connection
from ..redis.client import check_redis_connection
from ..services.auth import AuthenticatedOwner
from .dependencies import require_owner

router = APIRouter(tags=["Health & Status"])
settings = get_settings()


class HealthComponent(BaseModel):
    status: str
    latency_ms: float | None = None
    message: str | None = None
    profile_optional: bool | None = None
    version: str | None = None
    session_id: str | None = None
    session_label: str | None = None
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
    if not settings.OPENWA_API_KEY:
        return False, 0.0, "Gateway OpenWA não configurado"
    url = f"{settings.OPENWA_SERVER_URL}/api/health/ready"
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            response = await client.get(url, headers={"X-API-Key": settings.OPENWA_API_KEY})
        latency = (time.perf_counter() - started) * 1000.0
        if 200 <= response.status_code < 300:
            record_integration("openwa", "success", latency)
            return True, round(latency, 2), None
        record_integration("openwa", "error", latency)
        return False, round(latency, 2), f"Status HTTP {response.status_code}"
    except Exception:
        latency = (time.perf_counter() - started) * 1000.0
        record_integration("openwa", "error", latency)
        return False, round(latency, 2), "Gateway OpenWA não iniciado ou fora do profile ativo"


async def check_openwa_session() -> tuple[str | None, bool, float, str | None]:
    """Read only the normalized session state, never returning gateway JSON."""
    if not settings.OPENWA_API_KEY:
        return None, False, 0.0, "Gateway OpenWA não configurado"
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            response = await client.get(
                f"{settings.OPENWA_SERVER_URL}/api/sessions/{settings.OPENWA_SESSION_ID}",
                headers={"X-API-Key": settings.OPENWA_API_KEY},
            )
        latency = (time.perf_counter() - started) * 1000.0
        if response.status_code != 200:
            return None, False, round(latency, 2), f"Status HTTP {response.status_code}"
        state = response.json()
        value = str(state.get("status") or state.get("state") or "").lower()
        status_map = {
            "ready": "CONNECTED",
            "connected": "CONNECTED",
            "online": "CONNECTED",
            "qr_ready": "QR_REQUIRED",
            "qr": "QR_REQUIRED",
            "qr_required": "QR_REQUIRED",
            "action_required": "RELINK_REQUIRED",
            "relink_required": "RELINK_REQUIRED",
            "failed": "ERROR",
            "error": "ERROR",
        }
        normalized = status_map.get(value, "DISCONNECTED")
        secure = normalized == "CONNECTED" and state.get("engineLoaded") is True
        return normalized, secure, round(latency, 2), None
    except Exception:
        latency = (time.perf_counter() - started) * 1000.0
        return None, False, round(latency, 2), "Estado da sessão OpenWA indisponível"


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


async def read_persisted_openwa_state(
    db_ok: bool, tenant_id: UUID | None = None
) -> dict[str, object]:
    """Read durable checkpoints without exposing gateway payloads or secrets."""
    if not db_ok or not settings.OPENWA_API_KEY:
        return {"state": "unconfigured"}
    try:
        from sqlalchemy import select

        from ..db.models import ChannelSession, SessionAssignment
        from ..db.session import async_session_factory

        async with async_session_factory() as db:
            row = await db.scalar(
                select(ChannelSession).where(
                    ChannelSession.tenant_id == (tenant_id or UUID(settings.DEFAULT_TENANT_ID)),
                    ChannelSession.external_session_id == settings.OPENWA_SESSION_ID,
                )
            )
            assignment_count = len(
                (
                    await db.scalars(
                        select(SessionAssignment).where(
                            SessionAssignment.tenant_id
                            == (tenant_id or UUID(settings.DEFAULT_TENANT_ID)),
                            SessionAssignment.external_session_id
                            == settings.OPENWA_SESSION_ID,
                            SessionAssignment.status == "ACTIVE",
                        )
                    )
                ).all()
            )
        if row is None:
            return {"state": "not_provisioned"}
        return {
            "session_status": row.status,
            "engine_version": row.engine_version,
            "last_webhook": row.last_webhook_at.isoformat() if row.last_webhook_at else "unknown",
            "last_receipt": row.last_receipt_at.isoformat() if row.last_receipt_at else "unknown",
            "restart_count": row.restart_count,
            "last_failure_code": row.last_failure_code or "none",
            "shard": settings.OPENWA_SHARD_ID or "unknown",
            "active_owner_count": assignment_count,
        }
    except Exception:
        return {"state": "unavailable"}


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


async def build_health_report(
    response: Response, *, tenant_id: UUID | None = None
) -> dict[str, object]:
    db_ok, db_latency, db_error = await check_db_connection()
    redis_ok, redis_latency, redis_error = await check_redis_connection()
    worker_ok, worker_latency, worker_error = await check_worker_connection()
    openwa_ok, openwa_latency, openwa_error = await check_openwa_connection()
    observed_session_status, observed_session_secure, session_latency, session_error = (
        await check_openwa_session()
    )
    persisted_state = await read_persisted_openwa_state(db_ok, tenant_id)

    active_owner_count = persisted_state.get("active_owner_count")
    owner_count = active_owner_count if isinstance(active_owner_count, int) else 0
    connection = observed_session_status or str(
        persisted_state.get("session_status") or ("CONNECTED" if openwa_ok else "DISCONNECTED")
    )
    session_ready = connection == "CONNECTED" and (
        observed_session_secure or observed_session_status is None and openwa_ok
    )
    session_status = "healthy" if session_ready else (
        "inactive" if not settings.OPENWA_API_KEY else "unhealthy"
    )
    session_metric_label = hashlib.sha256(settings.OPENWA_SESSION_ID.encode()).hexdigest()[:12]
    last_webhook = persisted_state.get("last_webhook") or metrics.get_gauge(
        "ks_openwa_session_last_webhook_timestamp",
        labels={"session_id": session_metric_label},
    )
    last_receipt = persisted_state.get("last_receipt") or metrics.get_gauge(
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
            "session_label": session_metric_label,
            "owner_configured": bool(settings.OPENWA_API_KEY and settings.OPENWA_SESSION_ID),
        },
        "whatsapp_session": {
            "status": session_status,
            "latency_ms": session_latency if session_latency else openwa_latency,
            "message": session_error or openwa_error,
            "version": str(persisted_state.get("engine_version") or "v0.23.3"),
            "session_label": session_metric_label,
            "owner_configured": bool(settings.OPENWA_API_KEY and settings.OPENWA_SESSION_ID),
            "details": {
                "connection": connection,
                "relink_required": connection in {"QR_REQUIRED", "RELINK_REQUIRED"},
                "last_webhook": last_webhook if last_webhook is not None else "unknown",
                "last_receipt": last_receipt if last_receipt is not None else "unknown",
                "restart_count": persisted_state.get("restart_count", "unknown"),
                "memory": "unknown",
                "owner_or_shard": (
                    "conflict"
                    if owner_count > 1
                    else "unique"
                    if owner_count == 1
                    else "unassigned"
                ),
                "shard": persisted_state.get("shard", settings.OPENWA_SHARD_ID or "unknown"),
                "last_failure_code": persisted_state.get("last_failure_code", "unknown"),
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

    overall_healthy = db_ok and redis_ok and worker_ok and (
        not settings.OPENWA_COMMERCIAL_USE or session_ready
    )
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


@router.get(
    "/health/owner",
    response_model=HealthResponse,
    summary="Authenticated owner health details",
)
async def owner_health(
    response: Response,
    owner: AuthenticatedOwner = Depends(require_owner),
) -> dict[str, object]:
    """Expose operational session state only inside the owner-authenticated UI."""
    return await build_health_report(response, tenant_id=owner.tenant_id)
