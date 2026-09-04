from src.core.config import Settings


def test_external_postgres_url_uses_asyncpg_and_ssl() -> None:
    settings = Settings(
        DATABASE_BACKEND="neon",
        DATABASE_URL="postgresql://neondb_owner:example@ep-example.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require",
        DATABASE_SSL_MODE="auto",
    )

    assert settings.get_database_url() == (
        "postgresql+asyncpg://neondb_owner:example@ep-example.sa-east-1.aws.neon.tech/neondb"
    )
    assert settings.get_database_connect_args() == {"ssl": "require"}


def test_local_postgres_does_not_force_ssl() -> None:
    settings = Settings(DATABASE_BACKEND="local", DATABASE_SSL_MODE="disable")

    assert settings.get_database_connect_args() == {}
