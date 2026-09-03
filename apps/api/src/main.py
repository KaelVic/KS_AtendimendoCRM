import logging
import time
from contextlib import asynccontextmanager
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from .core.config import get_settings, validate_llm_settings, validate_openwa_settings
from .core.logging import setup_logging
from .core.observability import metrics
from .api.health import router as health_router
from .api.auth import router as auth_router
from .api.messages import router as messages_router, inbox_router
from .api.pending import router as pending_router
from .api.proposals import router as proposals_router
from .api.commercial import router as commercial_router
from .api.calendar import router as calendar_router
from .api.prospects import router as prospects_router
from .api.outreach import router as outreach_router
from .db.session import engine
from .redis.client import redis_client

settings = get_settings()
setup_logging(settings.LOG_LEVEL)
logger = logging.getLogger("ks_api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Iniciando KS Atendimento API...")
    validate_llm_settings(settings)
    validate_openwa_settings(settings)
    yield
    logger.info("Encerrando conexões de banco e Redis...")
    await engine.dispose()
    await redis_client.close()
    logger.info("KS Atendimento API finalizada.")


app = FastAPI(
    title="KS Atendimento IA API",
    description="API Modular para CRM, WhatsApp, Agente IA e Automação Comercial",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS restrito conforme AGENTS.md §17
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    """Propaga apenas IDs de correlação válidos e nunca confia em texto arbitrário."""
    incoming_id = request.headers.get("X-Correlation-ID")
    try:
        correlation_id = str(UUID(incoming_id)) if incoming_id else str(uuid4())
    except (ValueError, AttributeError):
        correlation_id = str(uuid4())

    request.state.correlation_id = correlation_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        metrics.inc("ks_http_errors_total", labels={"method": request.method})
        metrics.observe_latency("http", (time.perf_counter() - started) * 1000)
        raise
    metrics.inc(
        "ks_http_requests_total",
        labels={"method": request.method, "status_class": f"{response.status_code // 100}xx"},
    )
    if response.status_code >= 500:
        metrics.inc(
            "ks_http_errors_total",
            labels={"method": request.method, "status_class": "5xx"},
        )
    metrics.observe_latency("http", (time.perf_counter() - started) * 1000)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


# Inclui rotas de saúde
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(messages_router)
app.include_router(inbox_router)
app.include_router(pending_router)
app.include_router(proposals_router)
app.include_router(commercial_router)
app.include_router(calendar_router)
app.include_router(prospects_router)
app.include_router(outreach_router)


@app.get("/", summary="Root Endpoint")
async def root():
    return {
        "name": "KS Atendimento IA API",
        "status": "operational",
        "docs_url": "/docs",
        "health_url": "/health",
    }


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(
        "unhandled_request_error",
        extra={
            "correlation_id": getattr(request.state, "correlation_id", None),
            "exception_type": type(exc).__name__,
        },
    )
    return JSONResponse(
        status_code=500,
        content={
            "error_code": "INTERNAL_SERVER_ERROR",
            "message": "Ocorreu um erro interno. A equipe de engenharia foi notificada.",
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error_code": "VALIDATION_ERROR",
            "message": "Dados de entrada invÃ¡lidos",
            "correlation_id": getattr(request.state, "correlation_id", None),
            "details": [{"location": error.get("loc"), "type": error.get("type")} for error in exc.errors()],
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail: dict[str, object] = exc.detail if isinstance(exc.detail, dict) else {}
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "error_code": detail.get("error_code", "HTTP_ERROR"),
            "message": detail.get("message", "RequisiÃ§Ã£o nÃ£o autorizada"),
            "correlation_id": getattr(request.state, "correlation_id", None),
            "details": detail.get("details"),
        },
    )
