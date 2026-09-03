from src.core.config import Settings


def test_supabase_postgres_url_uses_asyncpg_and_ssl() -> None:
    settings = Settings(
        DATABASE_BACKEND="supabase",
        DATABASE_URL="postgresql://postgres:example@db.example.supabase.co:5432/postgres?sslmode=require",
        DATABASE_SSL_MODE="auto",
    )

    assert settings.get_database_url() == (
        "postgresql+asyncpg://postgres:example@db.example.supabase.co:5432/postgres"
    )
    assert settings.get_database_connect_args() == {"ssl": "require"}


def test_local_postgres_does_not_force_ssl() -> None:
    settings = Settings(DATABASE_BACKEND="local", DATABASE_SSL_MODE="disable")

    assert settings.get_database_connect_args() == {}
