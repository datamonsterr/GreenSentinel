"""TDD RED: B13 Security - Fail closed for ownerless cases (driver_id missing or None)."""

import pytest
from fastapi import HTTPException

from src.agents.tools.driver_tools import (
    get_case_timeline,
    get_driver_dispute_context,
)
from src.models.tool_contracts import ToolExecutionContext
from src.services.case_service import get_case_service
from src.services.driver_dispute_service import get_driver_dispute_service
from src.services.tool_execution import _scope


@pytest.fixture
def ownerless_case_id():
    """Seed an in-memory case with driver_id=None."""
    cs = get_case_service()
    case_id = "018f2f4e-0000-7000-8000-ownerless0001"
    cs._cases[case_id] = {
        "id": case_id,
        "organization_id": "018f2f4e-0000-7000-8000-000000000001",
        "assignment_id": None,
        "assigned_analyst_id": "an-001",
        "driver_id": None,
        "trip_id": None,
        "vehicle_id": None,
        "status": "active",
        "dispute_status": "in_dispute",
        "suspected_category": "ERR-01",
    }
    return case_id


def test_scope_fails_closed_for_ownerless_case(ownerless_case_id):
    """B13: _scope in tool_execution.py must treat driver_id=None as not owned by the driver (HTTP 404)."""
    ctx = ToolExecutionContext(
        actor_id="drv-attacker-001",
        organization_id="018f2f4e-0000-7000-8000-000000000001",
        roles=frozenset({"driver"}),
        case_id=ownerless_case_id,
        driver_id="drv-attacker-001",
        request_id="req-1",
        run_id="run-1",
        tool_call_id="call-1",
        turn_id="turn-1",
    )
    with pytest.raises(HTTPException) as exc_info:
        _scope(ctx)
    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail.lower()


def test_scope_fails_closed_when_both_case_and_context_driver_id_none(ownerless_case_id):
    """B13: Even if caller ctx.driver_id is None, ownerless case must still be rejected."""
    ctx = ToolExecutionContext(
        actor_id="drv-anon",
        organization_id="018f2f4e-0000-7000-8000-000000000001",
        roles=frozenset({"driver"}),
        case_id=ownerless_case_id,
        driver_id=None,
        request_id="req-1",
        run_id="run-1",
        tool_call_id="call-1",
        turn_id="turn-1",
    )
    with pytest.raises(HTTPException) as exc_info:
        _scope(ctx)
    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_get_driver_dispute_context_fails_closed_for_ownerless_case(ownerless_case_id):
    """B13: get_driver_dispute_context on ownerless case must raise 404."""
    service = get_driver_dispute_service()
    with pytest.raises(HTTPException) as exc_info:
        await service.get_driver_dispute_context(
            case_id=ownerless_case_id,
            driver_id="drv-attacker-001",
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_corroborate_traffic_conditions_fails_closed_for_ownerless_case(ownerless_case_id):
    """B13: corroborate_traffic_conditions on ownerless case must raise 404."""
    service = get_driver_dispute_service()
    with pytest.raises(HTTPException) as exc_info:
        await service.corroborate_traffic_conditions(
            case_id=ownerless_case_id,
            driver_id="drv-attacker-001",
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_driver_tools_fail_closed_for_ownerless_case(ownerless_case_id):
    """B13: Driver tools return NOT_FOUND (404) for ownerless cases, never access."""
    res_ctx = await get_driver_dispute_context.ainvoke(
        {
            "case_id": ownerless_case_id,
            "driver_id": "drv-attacker-001",
        }
    )
    assert res_ctx.get("status_code") == 404 or res_ctx.get("error_type") == "NOT_FOUND"

    res_timeline = await get_case_timeline.ainvoke(
        {
            "case_id": ownerless_case_id,
            "driver_id": "drv-attacker-001",
        }
    )
    assert res_timeline.get("status_code") == 404 or res_timeline.get("error_type") == "NOT_FOUND"
