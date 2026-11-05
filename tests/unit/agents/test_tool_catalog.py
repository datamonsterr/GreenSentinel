"""Tests for agent tool catalog, forbidden model capabilities, and trusted input boundaries.

Refs #60, #85.
"""

from __future__ import annotations

import pytest

from src.models.tool_contracts import ToolCatalogEntry
from src.services.tool_catalog import (
    ANALYST_SURFACE_NAMES,
    COCKPIT_SURFACE_NAMES,
    DRIVER_SURFACE_NAMES,
    FORBIDDEN_MODEL_COMMANDS,
    get_tool_catalog,
    model_input_schemas,
    model_tool_names,
)


def test_model_registry_excludes_human_commands():
    """Verify model-selectable tool sets never contain human-only actions."""
    for actor in ("analyst", "driver"):
        names = model_tool_names(actor)
        assert FORBIDDEN_MODEL_COMMANDS.isdisjoint(names), (
            f"Actor '{actor}' exposed forbidden commands: {FORBIDDEN_MODEL_COMMANDS.intersection(names)}"
        )

    catalog = get_tool_catalog()
    assert len(catalog) > 0
    assert all(isinstance(entry, ToolCatalogEntry) for entry in catalog)
    assert all(entry.purpose for entry in catalog)
    assert all(entry.input_schema is not None and entry.output_schema is not None for entry in catalog)
    assert all(entry.error_codes and entry.provenance_kind for entry in catalog)


def test_catalog_covers_all_surfaces():
    """Verify catalog accounts for all 16 analyst, 15 cockpit, and 6 driver tools."""
    catalog = get_tool_catalog()
    catalog_surfaces = {surface for entry in catalog for surface in entry.surface_names}

    assert ANALYST_SURFACE_NAMES.issubset(catalog_surfaces), (
        f"Missing analyst tools: {ANALYST_SURFACE_NAMES - catalog_surfaces}"
    )
    assert COCKPIT_SURFACE_NAMES.issubset(catalog_surfaces), (
        f"Missing cockpit tools: {COCKPIT_SURFACE_NAMES - catalog_surfaces}"
    )
    assert DRIVER_SURFACE_NAMES.issubset(catalog_surfaces), (
        f"Missing driver tools: {DRIVER_SURFACE_NAMES - catalog_surfaces}"
    )


def test_authority_is_not_in_model_input_schemas():
    """Verify server authority fields are strictly excluded from model schemas."""
    forbidden = {"actor_id", "organization_id", "roles", "permissions", "runtime_context"}
    for schema in model_input_schemas():
        properties = schema.get("properties", {})
        assert forbidden.isdisjoint(properties), (
            f"Schema '{schema.get('title', 'unknown')}' leaked authority fields: {forbidden.intersection(properties)}"
        )


def test_cockpit_declarations_exclude_forbidden_commands():
    """Verify Cockpit tool declarations do not offer write_ticket or human commands."""
    from src.rag.cockpit_agent import CockpitRAGAgent

    agent = CockpitRAGAgent()
    declarations = agent.get_tool_declarations()
    declared_names = {decl.name for decl in declarations}
    assert FORBIDDEN_MODEL_COMMANDS.isdisjoint(declared_names), (
        f"Cockpit declarations include forbidden commands: {FORBIDDEN_MODEL_COMMANDS.intersection(declared_names)}"
    )

    # Test offline router does not dispatch write_ticket_for_driver or human commands
    route = agent._offline_route("write a ticket for the driver")
    assert route != "write_ticket_for_driver", "Offline route directed to forbidden write_ticket_for_driver"


def test_graph_toolnode_excludes_forbidden_commands():
    """Verify LangGraph ToolNode binds only permitted model tools."""
    from src.agents.tools.analyst_tools import ANALYST_TOOLS
    from src.agents.tools.driver_tools import DRIVER_TOOLS

    analyst_tool_names = {getattr(t, "name", getattr(t, "__name__", str(t))) for t in ANALYST_TOOLS}
    assert FORBIDDEN_MODEL_COMMANDS.isdisjoint(analyst_tool_names), (
        f"Analyst ToolNode has forbidden commands: {FORBIDDEN_MODEL_COMMANDS.intersection(analyst_tool_names)}"
    )

    driver_tool_names = {getattr(t, "name", getattr(t, "__name__", str(t))) for t in DRIVER_TOOLS}
    assert FORBIDDEN_MODEL_COMMANDS.isdisjoint(driver_tool_names), (
        f"Driver ToolNode has forbidden commands: {FORBIDDEN_MODEL_COMMANDS.intersection(driver_tool_names)}"
    )


@pytest.mark.asyncio
async def test_typed_case_lookup_contract():
    """Verify typed case lookup returns strict ToolResult with real record provenance."""
    from unittest.mock import AsyncMock, patch

    from src.models.schemas import CaseDetailResponse
    from src.models.tool_contracts import ToolExecutionContext
    from src.services.tool_catalog import lookup_case_detail_typed

    ctx = ToolExecutionContext(
        actor_id="analyst-123",
        organization_id="org-green",
        roles=frozenset({"fraud_analyst"}),
        case_id="case-sample-01",
        driver_id="drv-123",
        request_id="req-abc",
        run_id="run-1",
        tool_call_id="call_test_1",
        turn_id="turn_1",
    )

    # 1. Non-existent case returns structured failed ToolResult (not raw exception dict)
    res_missing = await lookup_case_detail_typed("non-existent-case-id-12345", ctx)
    assert res_missing.status == "failed"
    assert res_missing.data is None
    assert res_missing.error is not None
    assert res_missing.error.code in ("NOT_FOUND", "INTERNAL_ERROR", "PERSISTENCE_UNAVAILABLE")
    assert len(res_missing.provenance) > 0
    assert res_missing.provenance[0].kind == "unavailable"

    # 2. Existing case returns succeeded ToolResult with real database provenance
    from src.models.schemas import FraudCaseSummary

    mock_summary = FraudCaseSummary(
        id="018f2f4e-a000-7000-8000-000000000001",
        status="pending",
        priority="high",
        priority_score=80,
    )
    mock_case = CaseDetailResponse(case=mock_summary)
    with patch("src.services.case_service.get_case_service") as mock_get_svc:
        mock_svc = mock_get_svc.return_value
        mock_svc.get_case_detail = AsyncMock(return_value=mock_case)
        res_found = await lookup_case_detail_typed("018f2f4e-a000-7000-8000-000000000001", ctx)
        assert res_found.status == "succeeded"
        assert res_found.error is None
        assert res_found.data is not None
        assert res_found.data["case"]["id"] == "018f2f4e-a000-7000-8000-000000000001"
        assert len(res_found.provenance) == 1
        assert res_found.provenance[0].kind == "database"
        assert res_found.provenance[0].source == "app.fraud_cases"
        assert res_found.provenance[0].record_ids == ["018f2f4e-a000-7000-8000-000000000001"]
