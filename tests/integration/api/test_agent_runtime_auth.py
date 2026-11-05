"""Public HTTP authorization regressions for the agent runtime."""

import pytest

from src.config import get_settings


@pytest.mark.asyncio
async def test_driver_headers_cannot_authenticate_a_production_request(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    get_settings.cache_clear()
    try:
        response = await client.get(
            "/api/v1/driver/cases/018f2f4e-5000-7000-8000-000000000001/dispute",
            headers={"X-Driver-ID": "driver-guest", "X-Role": "driver,admin"},
        )
        assert response.status_code == 401
    finally:
        get_settings.cache_clear()
