from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurações da aplicação validadas pelo Pydantic Settings."""

    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    APP_PORT: int = 8000
    WEB_PORT: int = 3000

    # Tenant Padrão (Piloto KaelSolutions)
    DEFAULT_TENANT_ID: str = "00000000-0000-0000-0000-000000000001"
    DEFAULT_TENANT_NAME: str = "KaelSolutions"
    ADMIN_EMAIL: str = "kaelvictor.devsolution@gmail.com"
    # Destinatário operacional; o domínio não possui e-mail hardcoded.
    OWNER_ALERT_EMAIL: str = ""
    EMAIL_PROVIDER: str = "fake"
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    PROPOSAL_STORAGE_ROOT: str = "./var/proposals"
    CONTRACT_TEMPLATE_VERSION: Optional[str] = None
    PAYMENT_LINK_CONFIG_VERSION: Optional[str] = None
    PAYMENT_LINK_ALLOWLIST_JSON: str = "[]"
    PAYMENT_WEBHOOK_SECRET: Optional[str] = None
    CALENDAR_PROVIDER: str = "fake"
    GOOGLE_CALENDAR_CREDENTIALS_JSON: Optional[str] = None
    CALENDAR_PERSONAL_ID: str = "personal"
    CALENDAR_ONBOARDING_ID: str = "Onboarding KaelSolutions"
    CALENDAR_TIMEZONE: str = "America/Sao_Paulo"
    OWNER_AUTH_TOKEN: Optional[str] = None
    TIMEZONE: str = "America/Sao_Paulo"

    # PostgreSQL
    POSTGRES_USER: str = "ks_user"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = "ks_atendimento"
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    DATABASE_URL: Optional[str] = None

    # Redis
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_URL: Optional[str] = None

    # OpenWA Gateway (rede interna Docker, v0.23.3)
    OPENWA_SERVER_URL: str = "http://openwa:2785"
    OPENWA_API_KEY: Optional[str] = None
    OPENWA_WEBHOOK_SECRET: Optional[str] = None
    OPENWA_SESSION_ID: str = "kaelsolutions_pilot"
    OPENWA_SHARD_ID: str = ""
    OPENWA_GATEWAY_ID: str = "00000000-0000-0000-0000-000000000002"
    OPENWA_OWNER_ID: str = "ks-api-pilot"
    OPENWA_LEASE_SECONDS: int = 30
    # ScrapeGraphAI is reachable only on the Docker internal network.
    SCRAPEGRAPH_SERVICE_URL: str = "http://scrapegraph:8081"
    SCRAPEGRAPH_SERVICE_TOKEN: Optional[str] = None
    SCRAPEGRAPH_CACHE_TTL_SECONDS: int = 86_400

    # Cold outreach is disabled against real infrastructure until explicitly configured.
    OUTREACH_PROVIDER: str = "fake"
    OUTREACH_APPROVAL_TTL_HOURS: int = 24
    OUTREACH_DAILY_LIMIT: int = 5
    OUTREACH_MIN_INTERVAL_SECONDS: int = 300

    # LLM provider. Gemini is opt-in so local tests never require a secret.
    LLM_PROVIDER: str = "fake"
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-1.5-flash"
    LLM_TIMEOUT_SECONDS: float = 12.0
    LLM_MAX_RETRIES: int = 2
    LLM_RATE_LIMIT: int = 30

    # Mídia: limites operacionais; retenção final depende da política do proprietário.
    MEDIA_MAX_BYTES: int = 25 * 1024 * 1024
    MEDIA_MAX_AUDIO_DURATION_SECONDS: float = 15 * 60
    MEDIA_MAX_IMAGE_PIXELS: int = 25_000_000
    MEDIA_MAX_IMAGE_DIMENSION: int = 2_048
    MEDIA_RETAIN_ORIGINALS: bool = True

    # Segurança e CORS
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://web:3000",
    ]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def get_database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    def get_redis_url(self) -> str:
        if self.REDIS_URL:
            return self.REDIS_URL
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_llm_settings(settings: Settings) -> None:
    if settings.LLM_PROVIDER.lower() == "gemini" and not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY obrigatória quando LLM_PROVIDER=gemini")
