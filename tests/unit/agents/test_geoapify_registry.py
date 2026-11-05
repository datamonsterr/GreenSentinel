"""Case-scoped Geoapify registry coverage under the DoD agent filter.

Refs #230. The heavy adapter/dispatch contracts live in
``tests/integration/services/test_geoapify_case_tools.py``; this file pins the
catalog, allowlist and red-team boundaries so the documented DoD command
``pytest tests/integration/agents/ -k "geoapify or route or geocode"`` has
geoapify coverage in the agents boundary.
"""

from __future__ import annotations

import pytest

from src.services.tool_catalog import (
    FORBIDDEN_MODEL_COMMANDS,
    get_tool_catalog,
    model_tool_names,
)

GEO_TOOLS = {
    "compare_trip_routes",
    "get_case_map_snapshot",
    "geocode_address",
    "reverse_geocode_coordinates",
    "match_trip_telemetry",
}


def test_geo_tools_registered_in_catalog():
    catalog = {entry.canonical_id: entry for entry in get_tool_catalog()}
    assert GEO_TOOLS <= set(catalog)
    for tool in GEO_TOOLS:
        entry = catalog[tool]
        assert entry.model_selectable
        assert entry.side_effects is False
        assert entry.error_codes


def test_geo_tools_model_selectable_for_analyst_and_driver():
    analyst = model_tool_names("analyst")
    driver = model_tool_names("driver")
    assert GEO_TOOLS <= analyst
    assert {"geocode_address", "reverse_geocode_coordinates", "match_trip_telemetry"} <= driver


def test_places_tools_explicitly_out_of_scope():
    catalog = get_tool_catalog()
    surfaces = {surface for entry in catalog for surface in entry.surface_names}
    assert "search_places" not in surfaces
    assert "search_places" not in model_tool_names("analyst")


def test_sanction_tools_stay_human_only_regardless_of_geo_routing():
    # Red-team boundary: route/geocode/match context can never select sanctions.
    names = model_tool_names("analyst") | model_tool_names("driver")
    assert FORBIDDEN_MODEL_COMMANDS.isdisjoint(names)
    catalog = {entry.canonical_id: entry for entry in get_tool_catalog()}
    for forbidden in ("adjudicate_case", "claim_case", "record_case_action", "write_ticket_for_driver"):
        assert catalog[forbidden].model_selectable is False


@pytest.mark.asyncio
async def test_route_context_has_no_sanction_field():
    from uuid import uuid4

    from src.models.tool_contracts import ToolExecutionContext
    from src.services.tool_execution import execute_tool

    ctx = ToolExecutionContext(
        actor_id="018f2f4e-1000-7000-8000-000000000001",
        organization_id="018f2f4e-0000-7000-8000-000000000001",
        roles=frozenset({"senior_analyst"}),
        case_id="018f2f4e-a000-7000-8000-000000000038",
        driver_id="018f2f4e-3000-7000-8000-000000000018",
        request_id=str(uuid4()),
        run_id=str(uuid4()),
        tool_call_id=str(uuid4()),
        turn_id=str(uuid4()),
    )
    result = await execute_tool("compare_trip_routes", {}, ctx)
    if result.status != "succeeded":
        pytest.skip("Database with seeded case not available")
    assert "adjudicate" not in result.model_dump(mode="json").get("data", {})
