"""ASGI/provider transport contracts; fixture identity, scheduling and public Hanoi data."""

import asyncio
import json

import anyio.to_thread
import pytest
from httpx import ASGITransport, AsyncClient

from src.api.auth import Principal, require_principal
from src.main import app
from src.services import routing_service


@pytest.fixture
def provider_contract_runtime(monkeypatch):
    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    async def inline_anyio(function, *args, **scheduler_options):
        return function(*args)

    async def identity():
        return Principal(id="fixture-operator", organization_id="fixture-org", roles=frozenset({"demo_operator"}))

    overrides = dict(app.dependency_overrides)
    app.dependency_overrides[require_principal] = identity
    monkeypatch.setattr(asyncio, "to_thread", inline)
    monkeypatch.setattr(anyio.to_thread, "run_sync", inline_anyio)
    monkeypatch.setenv("ROUTING_PROVIDER", "geoapify")
    monkeypatch.setenv("GEOAPIFY_API_KEY", "fixture-only")
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(overrides)


@pytest.mark.asyncio
async def test_http_route_contract_preserves_disjoint_geometry(provider_contract_runtime, monkeypatch):
    geometry = {
        "type": "MultiLineString",
        "coordinates": [
            [[105.83, 21.02], [105.84, 21.03]],
            [[105.85, 21.04], [105.86, 21.05]],
        ],
    }

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return None

        def read(self):
            return json.dumps(
                {"features": [{"geometry": geometry, "properties": {"distance": 1317, "time": 87.581}}]}
            ).encode()

    monkeypatch.setattr(routing_service, "urlopen", lambda *_a, **_kw: Response())
    async with AsyncClient(transport=ASGITransport(app), base_url="http://fixture") as client:
        result = await client.post(
            "/test/api/v1/routes/resolve",
            headers={"X-Test-Context": "true"},
            json={
                "origin": [105.83, 21.02],
                "pickup": [105.84, 21.03],
                "destination": [105.86, 21.05],
            },
        )
    assert result.status_code == 200
    body = result.json()
    assert body["route_geometry"]["coordinates"] == geometry["coordinates"] * 2
    assert body["route_geometry"]["type"] == "MultiLineString"
    assert body["pickup_route"]["duration_s"] == 87.581
    assert body["pickup_route"]["provenance"]["mode"] == "motorcycle"


@pytest.mark.asyncio
async def test_http_route_contract_failure_is_safe_503(provider_contract_runtime, monkeypatch):
    def failed(*_a, **_kw):
        raise TimeoutError("fixture-canary private provider URL")

    monkeypatch.setattr(routing_service, "urlopen", failed)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://fixture") as client:
        result = await client.post(
            "/test/api/v1/routes/resolve",
            headers={"X-Test-Context": "true"},
            json={
                "origin": [105.83, 21.02],
                "pickup": [105.84, 21.03],
                "destination": [105.86, 21.05],
            },
        )
    assert result.status_code == 503
    assert result.json() == {"detail": "Route provider unavailable"}
