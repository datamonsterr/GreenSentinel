"""Unit tests for issue #457: waypoints ordering, legacy form, and 4 km start boundary."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from src.api import test_routes
from src.api.auth import Principal
from src.api.test_routes import create_definition_revision, resolve_simulation_route
from src.models.test_simulation import (
    DriverSimConfig,
    GeoJsonLineString,
    LatLon,
    RouteResolveRequest,
    RouteWaypoint,
    TestDefinitionRevisionCreate,
    TestStopSnapshot,
)
from src.services import routing_service
from src.services.driver_directory import (
    DriverRecord,
    HybridDriverDirectory,
    InMemoryDriverDirectory,
    set_driver_directory,
)
from src.services.route_analytics import haversine_distance_m

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
            license_plate="29A-888.88",
        )
    )
    yield dir_svc
    set_driver_directory(HybridDriverDirectory())


@pytest.fixture(autouse=True)
def inline_scheduler(monkeypatch):
    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(test_routes.asyncio, "to_thread", run_inline)


def _mock_leg(start: list[float], end: list[float]) -> dict:
    return {
        "geometry": {"type": "LineString", "coordinates": [start, end]},
        "distance_m": 500,
        "duration_s": 60.0,
        "provider": "mock-osrm",
        "traffic_model": "free_flow",
        "provenance": {"source": "mock"},
    }


def test_route_resolve_accepts_typed_waypoints_per_leg(monkeypatch):
    calls: list[tuple[list[float], list[float]]] = []

    def mock_fetch(start, end, *args, **kwargs):
        calls.append((start, end))
        return _mock_leg(start, end)

    monkeypatch.setattr(routing_service, "fetch_route", mock_fetch)

    origin = [105.80, 21.00]
    pickup = [105.85, 21.05]
    dest = [105.90, 21.10]
    wp_pickup = {"lon": 105.82, "lat": 21.02, "leg": "pickup"}
    wp_dest = {"lon": 105.87, "lat": 21.07, "leg": "destination"}

    payload = RouteResolveRequest(
        origin=origin,
        pickup=pickup,
        destination=dest,
        waypoints=[wp_pickup, wp_dest],
    )

    result = asyncio.run(resolve_simulation_route(payload, x_test_context="true"))

    # Origin -> pickup waypoint -> pickup -> dest waypoint -> destination
    assert len(calls) == 4
    assert calls[0] == (origin, [105.82, 21.02])
    assert calls[1] == ([105.82, 21.02], pickup)
    assert calls[2] == (pickup, [105.87, 21.07])
    assert calls[3] == ([105.87, 21.07], dest)

    # Waypoints preserved in response
    assert hasattr(result, "waypoints")
    assert len(result.waypoints) == 2
    assert result.waypoints[0].leg == "pickup"
    assert result.waypoints[1].leg == "destination"

    # Pickup route ends at pickup; destination route starts at pickup
    assert result.pickup_route.coordinates[-1] == pickup
    assert result.destination_route.coordinates[0] == pickup


def test_route_resolve_legacy_array_waypoints_treated_as_pickup_leg(monkeypatch):
    calls: list[tuple[list[float], list[float]]] = []

    def mock_fetch(start, end, *args, **kwargs):
        calls.append((start, end))
        return _mock_leg(start, end)

    monkeypatch.setattr(routing_service, "fetch_route", mock_fetch)

    origin = [105.80, 21.00]
    pickup = [105.85, 21.05]
    dest = [105.90, 21.10]
    wp1 = [105.81, 21.01]
    wp2 = [105.82, 21.02]

    payload = RouteResolveRequest(
        origin=origin,
        pickup=pickup,
        destination=dest,
        waypoints=[wp1, wp2],
    )

    result = asyncio.run(resolve_simulation_route(payload, x_test_context="true"))

    # Both legacy waypoints are routed on the pickup leg; dest leg has 1 call
    assert len(calls) == 4
    assert calls[0] == (origin, wp1)
    assert calls[1] == (wp1, wp2)
    assert calls[2] == (wp2, pickup)
    assert calls[3] == (pickup, dest)

    assert result.pickup_route.coordinates[-1] == pickup
    assert result.destination_route.coordinates[0] == pickup


def test_route_resolve_preserves_given_order_on_destination_leg(monkeypatch):
    calls: list[tuple[list[float], list[float]]] = []

    def mock_fetch(start, end, *args, **kwargs):
        calls.append((start, end))
        return _mock_leg(start, end)

    monkeypatch.setattr(routing_service, "fetch_route", mock_fetch)

    origin = [105.80, 21.00]
    pickup = [105.85, 21.05]
    dest = [105.90, 21.10]
    wp_d1 = RouteWaypoint(lon=105.86, lat=21.06, leg="destination")
    wp_d2 = RouteWaypoint(lon=105.88, lat=21.08, leg="destination")

    payload = RouteResolveRequest(
        origin=origin,
        pickup=pickup,
        destination=dest,
        waypoints=[wp_d1, wp_d2],
    )

    result = asyncio.run(resolve_simulation_route(payload, x_test_context="true"))

    assert len(calls) == 4
    # Leg 1: origin -> pickup
    assert calls[0] == (origin, pickup)
    # Leg 2: pickup -> wp_d1
    assert calls[1] == (pickup, [105.86, 21.06])
    # Leg 3: wp_d1 -> wp_d2
    assert calls[2] == ([105.86, 21.06], [105.88, 21.08])
    # Leg 4: wp_d2 -> dest
    assert calls[3] == ([105.88, 21.08], dest)

    assert result.destination_route.distance_m == 1500


def test_4km_boundary_accepts_3999m(monkeypatch):
    principal = Principal(id="operator", organization_id=ORG_A, roles=frozenset())
    plan_id = uuid4()

    created_payloads = []

    class MockRepo:
        def get_plan(self, pid, organization_id):
            return {"id": pid, "organization_id": organization_id}

        def create_definition_revision(self, payload, organization_id):
            created_payloads.append(payload)
            return payload

    monkeypatch.setattr(test_routes, "get_simulation_runner", lambda: SimpleNamespace(repository=MockRepo()))

    pickup_coords = (105.8520, 21.0278)
    lat_3999 = pickup_coords[1] + (3999.0 / 111195.0)
    actual_dist = haversine_distance_m((pickup_coords[0], lat_3999), pickup_coords)
    assert 3998.0 <= actual_dist <= 3999.5

    payload = TestDefinitionRevisionCreate(
        plan_id=plan_id,
        route_geometry=GeoJsonLineString(coordinates=[[pickup_coords[0], lat_3999], list(pickup_coords)]),
        driver_config=DriverSimConfig(driver_id=str(DRIVER_A_ID)),
        initial_snapshot=TestStopSnapshot(location=LatLon(latitude=lat_3999, longitude=pickup_coords[0])),
        pickup_snapshot=TestStopSnapshot(location=LatLon(latitude=pickup_coords[1], longitude=pickup_coords[0])),
    )

    res = asyncio.run(create_definition_revision(payload, x_test_context="true", principal=principal))
    assert res is not None
    assert len(created_payloads) == 1


def test_4km_boundary_rejects_4001m(monkeypatch):
    principal = Principal(id="operator", organization_id=ORG_A, roles=frozenset())
    plan_id = uuid4()

    class MockRepo:
        def get_plan(self, pid, organization_id):
            return {"id": pid, "organization_id": organization_id}

        def create_definition_revision(self, payload, organization_id):
            return payload

    monkeypatch.setattr(test_routes, "get_simulation_runner", lambda: SimpleNamespace(repository=MockRepo()))

    pickup_coords = (105.8520, 21.0278)
    lat_4001 = pickup_coords[1] + (4001.0 / 111195.0)
    actual_dist = haversine_distance_m((pickup_coords[0], lat_4001), pickup_coords)
    assert actual_dist > 4000.0

    payload = TestDefinitionRevisionCreate(
        plan_id=plan_id,
        route_geometry=GeoJsonLineString(coordinates=[[pickup_coords[0], lat_4001], list(pickup_coords)]),
        driver_config=DriverSimConfig(driver_id=str(DRIVER_A_ID)),
        initial_snapshot=TestStopSnapshot(location=LatLon(latitude=lat_4001, longitude=pickup_coords[0])),
        pickup_snapshot=TestStopSnapshot(location=LatLon(latitude=pickup_coords[1], longitude=pickup_coords[0])),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(create_definition_revision(payload, x_test_context="true", principal=principal))

    assert exc_info.value.status_code == 422
    assert "4000" in str(exc_info.value.detail) or "exceed" in str(exc_info.value.detail).lower()


def test_max_start_to_pickup_m_constant_exposed(monkeypatch):
    from src.models.test_simulation import MAX_START_TO_PICKUP_M

    assert MAX_START_TO_PICKUP_M == 4000
