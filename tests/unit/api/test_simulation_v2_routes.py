"""Tests for simulation v2 endpoints: geocoding and Redis production publishing."""

import pytest

from src.api.auth import Principal
from src.api.test_routes import geocode_location, resolve_simulation_route
from src.models.test_simulation import (
    DriverSimConfig,
    GeoJsonLineString,
    PassengerSimConfig,
    RouteResolveRequest,
    TestDefinitionRevisionCreate,
    TestPlanCreate,
    TestRunCreate,
)
from src.services.test_simulation_runner import get_simulation_runner

ORG = "018f2f4e-0000-7000-8000-000000000001"
PRINCIPAL = Principal("operator", ORG, frozenset())


@pytest.mark.asyncio
async def test_geocode_location_fallback_returns_matching_landmarks(monkeypatch):
    monkeypatch.setenv("GEOAPIFY_API_KEY", "")
    res = await geocode_location(text="Hoàn Kiếm", limit=3, x_test_context="true")
    assert len(res.results) > 0
    first = res.results[0]
    assert "Hoàn Kiếm" in first.formatted
    assert first.lat == pytest.approx(21.0285, rel=1e-3)
    assert first.lon == pytest.approx(105.8524, rel=1e-3)


@pytest.mark.asyncio
async def test_geocode_location_accent_insensitive():
    res = await geocode_location(text="keangnam", limit=3, x_test_context="true")
    assert any("Keangnam" in r.formatted for r in res.results)


@pytest.mark.asyncio
async def test_geocode_location_never_invents_custom_address():
    custom_text = "Tòa nhà FPT Cầu Giấy"
    res = await geocode_location(text=custom_text, limit=5, x_test_context="true")
    assert len(res.results) > 0
    assert all(custom_text not in r.formatted for r in res.results)


@pytest.mark.asyncio
async def test_resolve_simulation_route_with_waypoints(monkeypatch):
    import src.services.routing_service as routing_service

    responses = iter(
        [
            {
                "routes": [
                    {
                        "geometry": {"type": "LineString", "coordinates": [[105.83, 21.02], [105.835, 21.025]]},
                        "distance": 500,
                        "duration": 60,
                    }
                ]
            },
            {
                "routes": [
                    {
                        "geometry": {"type": "LineString", "coordinates": [[105.835, 21.025], [105.84, 21.03]]},
                        "distance": 600,
                        "duration": 70,
                    }
                ]
            },
            {
                "routes": [
                    {
                        "geometry": {"type": "LineString", "coordinates": [[105.84, 21.03], [105.86, 21.05]]},
                        "distance": 2000,
                        "duration": 200,
                    }
                ]
            },
        ]
    )

    class DummyResponse:
        def __init__(self, data):
            import json

            self.data = json.dumps(data).encode("utf-8")
            self.status = 200

        def read(self):
            return self.data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(routing_service, "urlopen", lambda *_a, **_kw: DummyResponse(next(responses)))

    req = RouteResolveRequest(
        origin=[105.83, 21.02],
        pickup=[105.84, 21.03],
        destination=[105.86, 21.05],
        waypoints=[[105.835, 21.025]],
    )
    res = await resolve_simulation_route(req, x_test_context="true")
    assert res.provider == "osrm"
    assert res.pickup_route.distance_m == 1100
    assert res.pickup_route.coordinates == [
        [105.83, 21.02],
        [105.835, 21.025],
        [105.84, 21.03],
    ]
    assert res.route_geometry.coordinates == [
        [105.83, 21.02],
        [105.835, 21.025],
        [105.84, 21.03],
        [105.86, 21.05],
    ]


@pytest.mark.asyncio
async def test_apply_control_fast_complete():
    from src.api.test_routes import apply_control
    from src.models.test_simulation import TestControlCommand

    runner = get_simulation_runner()
    plan = runner.repository.create_plan(TestPlanCreate(name="Fast Complete Plan"), ORG)
    definition = runner.repository.create_definition_revision(
        TestDefinitionRevisionCreate(
            plan_id=plan.id,
            route_geometry=GeoJsonLineString(
                coordinates=[[105.8524, 21.0285], [105.8497, 21.0118], [105.8342, 21.0345]]
            ),
            driver_config=DriverSimConfig(speed_mps=15.0, driver_id="drv-v2-002"),
            passenger_config=PassengerSimConfig(passenger_id="pass-v2-002"),
            fault_configs=[],
            messages=[],
        ),
        ORG,
    )
    run = runner.repository.create_run(
        TestRunCreate(definition_revision_id=definition.id), total_steps=50, organization_id=ORG
    )

    # Start run and then immediately fast-complete
    await runner.start_run(run.id)
    cmd = TestControlCommand(command="FAST_COMPLETE", payload={})
    res = await apply_control(run.id, cmd, x_test_context="true", principal=PRINCIPAL)
    assert res == {"status": "accepted", "command": "FAST_COMPLETE"}
    assert runner._fast_forward.get(run.id) is True
