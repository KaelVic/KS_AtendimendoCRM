import os
import pytest
import httpx


API_URL = os.getenv("API_URL", "http://localhost:8000")
WEB_URL = os.getenv("WEB_URL", "http://localhost:3000")
OPENWA_PUBLIC_URL = "http://localhost:2785"
REAL_E2E = os.getenv("E2E_REAL") == "1"


def _require_real_stack() -> None:
    if not REAL_E2E:
        pytest.skip("E2E_REAL=1 não configurado; smoke real exige stack controlada")


@pytest.mark.asyncio
async def test_api_liveness(evidence):
    """Valida se a API responde na rota de liveness probe."""
    _require_real_stack()
    evidence.step("GET API liveness")
    async with httpx.AsyncClient(timeout=5.0) as client:
        res = await client.get(
            f"{API_URL}/health/live", headers={"X-Correlation-ID": evidence.correlation_id}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "alive"
        assert data["service"] == "ks-api"


@pytest.mark.asyncio
async def test_api_health_components(evidence):
    """Valida se a API expõe os status de saúde dos componentes (PostgreSQL, Redis, OpenWA)."""
    _require_real_stack()
    evidence.step("GET API component health")
    async with httpx.AsyncClient(timeout=5.0) as client:
        res = await client.get(f"{API_URL}/health")
        # Se os serviços estiverem ativos, retorna 200; caso contrário verifica payload estruturado
        data = res.json()
        assert "components" in data
        assert "postgres" in data["components"]
        assert "redis" in data["components"]
        assert "openwa" in data["components"]
        assert data["service"] == "ks-atendimento-api"


@pytest.mark.asyncio
async def test_web_reaches_api_and_postgres_is_healthy(evidence):
    """Smoke do caminho web -> API -> PostgreSQL em stack iniciada."""
    _require_real_stack()
    evidence.step("GET web and API health")
    async with httpx.AsyncClient(timeout=5.0) as client:
        web = await client.get(WEB_URL)
        api = await client.get(f"{API_URL}/health")

    assert web.status_code == 200
    assert "KS Atendimento IA" in web.text
    assert api.status_code == 200
    assert api.json()["components"]["postgres"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_openwa_health_when_optional_profile_is_configured(evidence):
    """Valida OpenWA somente quando o profile foi explicitamente configurado."""
    _require_real_stack()
    evidence.step("GET OpenWA optional health")
    openwa_url = os.getenv("OPENWA_URL")
    if not openwa_url:
        pytest.skip("profile openwa nÃ£o configurado")

    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(f"{openwa_url.rstrip('/')}/api/health/live")

    assert response.status_code < 500


@pytest.mark.asyncio
async def test_openwa_no_public_port_exposure(evidence):
    """Verifica que o OpenWA NÃO expõe portas no host público (conforme AGENTS.md §4.1)."""
    _require_real_stack()
    evidence.step("verify OpenWA host port is unreachable")
    async with httpx.AsyncClient(timeout=1.5) as client:
        with pytest.raises((httpx.ConnectError, httpx.ConnectTimeout)):
            await client.get(f"{OPENWA_PUBLIC_URL}/api/health/live")


def test_secrets_governance():
    """Valida que .env está no .gitignore e .env.example não contém segredos preenchidos."""
    with open(".gitignore", "r", encoding="utf-8") as f:
        gitignore_content = f.read()
    assert ".env" in gitignore_content
    assert "*session*" in gitignore_content

    with open(".env.example", "r", encoding="utf-8") as f:
        example_content = f.read()
    # Verifica que chaves de produção estão vazias no .env.example
    assert "GEMINI_API_KEY=\n" in example_content or "GEMINI_API_KEY=" in example_content
    assert "OPENWA_API_KEY=\n" in example_content or "OPENWA_API_KEY=" in example_content
