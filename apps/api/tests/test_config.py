from src.core.config import Settings


def test_default_settings():
    settings = Settings()
    assert settings.ENVIRONMENT in ["development", "test", "production"]
    assert settings.DEFAULT_TENANT_ID == "00000000-0000-0000-0000-000000000001"
    assert "postgresql+asyncpg://" in settings.get_database_url()
    assert "redis://" in settings.get_redis_url()
    assert settings.OPENWA_SERVER_URL.startswith("http")
