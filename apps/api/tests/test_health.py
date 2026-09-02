import pytest
from unittest.mock import AsyncMock, patch
from httpx import ASGITransport, AsyncClient
from src.main import app


@pytest.mark.asyncio
async def test_liveness_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"
        assert data["service"] == "ks-api"


@pytest.mark.asyncio
async def test_liveness_propagates_valid_correlation_id():
    correlation_id = "123e4567-e89b-12d3-a456-426614174000"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live", headers={"X-Correlation-ID": correlation_id})

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == correlation_id


@pytest.mark.asyncio
async def test_liveness_replaces_invalid_correlation_id():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live", headers={"X-Correlation-ID": "untrusted"})

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] != "untrusted"


@pytest.mark.asyncio
async def test_health_endpoint_healthy_components():
    with (
        patch("src.api.health.check_db_connection", new_callable=AsyncMock) as mock_db,
        patch("src.api.health.check_redis_connection", new_callable=AsyncMock) as mock_redis,
        patch("src.api.health.check_worker_connection", new_callable=AsyncMock) as mock_worker,
        patch("src.api.health.check_openwa_connection", new_callable=AsyncMock) as mock_openwa,
    ):
        mock_db.return_value = (True, 1.2, None)
        mock_redis.return_value = (True, 0.8, None)
        mock_worker.return_value = (True, 0.4, None)
        mock_openwa.return_value = (True, 2.5, None)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["components"]["postgres"]["status"] == "healthy"
            assert data["components"]["redis"]["status"] == "healthy"
            assert data["components"]["openwa"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_health_endpoint_degraded_when_db_down():
    with (
        patch("src.api.health.check_db_connection", new_callable=AsyncMock) as mock_db,
        patch("src.api.health.check_redis_connection", new_callable=AsyncMock) as mock_redis,
        patch("src.api.health.check_worker_connection", new_callable=AsyncMock) as mock_worker,
        patch("src.api.health.check_openwa_connection", new_callable=AsyncMock) as mock_openwa,
    ):
        mock_db.return_value = (False, 10.0, "Connection refused")
        mock_redis.return_value = (True, 0.5, None)
        mock_worker.return_value = (True, 0.4, None)
        mock_openwa.return_value = (False, 0.0, "OpenWA inactive")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "unhealthy"
            assert data["components"]["postgres"]["status"] == "unhealthy"
            assert data["components"]["redis"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_health_endpoint_degraded_when_worker_heartbeat_is_missing():
    with (
        patch("src.api.health.check_db_connection", new_callable=AsyncMock) as mock_db,
        patch("src.api.health.check_redis_connection", new_callable=AsyncMock) as mock_redis,
        patch("src.api.health.check_worker_connection", new_callable=AsyncMock) as mock_worker,
        patch("src.api.health.check_openwa_connection", new_callable=AsyncMock) as mock_openwa,
    ):
        mock_db.return_value = (True, 1.0, None)
        mock_redis.return_value = (True, 0.5, None)
        mock_worker.return_value = (False, 0.4, "Heartbeat do worker ausente ou expirado")
        mock_openwa.return_value = (False, 0.0, "OpenWA inactive")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

    assert response.status_code == 503
    assert response.json()["components"]["worker"]["status"] == "unhealthy"
