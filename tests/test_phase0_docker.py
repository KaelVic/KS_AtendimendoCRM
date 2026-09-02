from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_web_docker_context_contains_public_directory() -> None:
    public_directory = REPOSITORY_ROOT / "apps" / "web" / "public"

    assert public_directory.is_dir(), (
        "apps/web/Dockerfile copia /app/public, mas o diretório não existe no contexto"
    )
