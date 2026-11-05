import pytest

from src.config import get_settings


@pytest.mark.asyncio
async def test_observability_summary_requires_authentication_in_production(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    get_settings.cache_clear()
    try:
        response = await client.get("/api/v1/observability/summary")
        assert response.status_code == 401
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_analyst_can_read_privacy_safe_observability_summary(client):
    response = await client.get(
        "/api/v1/observability/summary",
        headers={"X-Role": "analyst", "X-Principal-ID": "analyst-test"},
    )
    assert response.status_code == 200
    summary = response.json()
    assert {"run_count", "latency_ms", "tools", "model", "quality", "benchmark", "tracing"} <= summary.keys()
    assert "case_id" not in str(summary)
    assert "driver_id" not in str(summary)


@pytest.mark.asyncio
async def test_driver_cannot_read_observability_summary(client):
    response = await client.get(
        "/api/v1/observability/summary",
        headers={"X-Role": "driver", "X-Driver-ID": "driver-test"},
    )
    assert response.status_code == 403
