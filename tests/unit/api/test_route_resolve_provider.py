import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from src.api import test_routes
from src.api.auth import Principal
from src.api.test_routes import resolve_simulation_route
from src.models.test_simulation import (
    DriverSimConfig,
    RouteResolveRequest,
    RouteResolveResponse,
)
from src.models.test_simulation import TestDefinitionRevisionCreate as DefinitionCreate
from src.services import routing_service
from src.services.driver_directory import (
    DriverRecord,
    HybridDriverDirectory,
    InMemoryDriverDirectory,
    set_driver_directory,
)

ORG_A = "018f2f4e-0000-7000-8000-000000000001"
DRIVER_A_ID = UUID("018f2f4e-3000-7000-8000-000000000011")


@pytest.fixture(autouse=True)
def setup_test_drivers():
    """Seed active Clerk-linked driver for test organization into in-memory driver directory."""
    dir_svc = InMemoryDriverDirectory()
    set_driver_directory(dir_svc)

    dir_svc.register_driver(
        DriverRecord(
            driver_id=DRIVER_A_ID,
            organization_id=ORG_A,
            principal_id=UUID("018f2f4e-2000-7000-8000-000000000011"),
            external_subject="user_clerk_a1",
            display_name="Nguyen Van A1",
            email="driver.a1@example.com",
            account_status="active",
        )
    )
    yield dir_svc
    set_driver_directory(HybridDriverDirectory())


@pytest.fixture(autouse=True)
def inline_scheduler(monkeypatch):
    """Isolate worker scheduling; exercise the real service and provider transports."""

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(test_routes.asyncio, "to_thread", run_inline)


def test_route_handler_returns_503_without_fallback(monkeypatch):
    def unavailable(*_a, **_kw):
        raise TimeoutError("fixture-only")

    monkeypatch.setattr(routing_service, "urlopen", unavailable)
    payload = RouteResolveRequest(origin=[105.83, 21.02], pickup=[105.84, 21.03], destination=[105.86, 21.05])
    with pytest.raises(HTTPException) as error:
        asyncio.run(resolve_simulation_route(payload, x_test_context="true"))
    assert error.value.status_code == 503
    assert error.value.detail == "Route provider unavailable"


def test_route_response_preserves_multiline_leg_shape():
    geometry = {
        "type": "MultiLineString",
        "coordinates": [
            [[105.83, 21.02], [105.84, 21.03]],
            [[105.85, 21.04], [105.86, 21.05]],
        ],
    }
    leg = {
        "coordinates": geometry["coordinates"],
        "distance_m": 1317,
        "duration_s": 87.581,
        "provider": "geoapify",
        "traffic_model": "approximated",
        "provenance": {"source": "geoapify", "advisory": True},
    }
    response = RouteResolveResponse(
        route_geometry=geometry, pickup_route=leg, destination_route=leg, provider="geoapify"
    )
    assert response.model_dump()["route_geometry"] == geometry
    assert response.pickup_route.duration_s == 87.581
    assert response.pickup_route.model_dump()["provenance"] == {"source": "geoapify", "advisory": True}


@pytest.mark.parametrize("available", [False, True])
def test_definition_never_stores_waypoint_shortcut_on_unavailable_or_disjoint_route(monkeypatch, available):
    import json

    principal = Principal(id="operator", organization_id=ORG_A, roles=frozenset())
    calls = []

    class Repository:
        def get_plan(self, _id, organization_id):
            assert organization_id == principal.organization_id
            return {"id": _id, "organization_id": organization_id}

        def create_definition_revision(self, payload, organization_id):
            assert organization_id == principal.organization_id
            calls.append(payload)
            return payload

    monkeypatch.setattr(test_routes, "get_simulation_runner", lambda: SimpleNamespace(repository=Repository()))

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return None

        def read(self):
            return json.dumps(
                {
                    "routes": [
                        {
                            "geometry": {
                                "type": "MultiLineString",
                                "coordinates": [
                                    [[105.83, 21.02], [105.84, 21.03]],
                                    [[105.85, 21.04], [105.86, 21.05]],
                                ],
                            },
                            "distance": 10,
                            "duration": 2,
                        }
                    ]
                }
            ).encode()

    def transport(*_a, **_kw):
        if available:
            return Response()
        raise TimeoutError

    monkeypatch.setattr(routing_service, "urlopen", transport)
    payload = DefinitionCreate(
        plan_id=uuid4(),
        driver_config=DriverSimConfig(driver_id=str(DRIVER_A_ID)),
        route_geometry={
            "type": "LineString",
            "coordinates": [
                [105.83, 21.02],
                [105.84, 21.03],
                [105.86, 21.05],
            ],
        },
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(test_routes.create_definition_revision(payload, x_test_context="true", principal=principal))
    assert error.value.status_code == (422 if available else 503)
    assert calls == []
