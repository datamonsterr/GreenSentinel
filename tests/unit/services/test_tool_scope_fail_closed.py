"""TDD RED/GREEN: _scope in tool_execution.py must fail closed on DB errors in
production and must only use the in-memory fallback when app_env=="test" and
test_auth_enabled, mirroring require_case_scope (src/services/access_control.py).
"""

import pytest
from fastapi import HTTPException

from src.config import Settings
from src.models.tool_contracts import ToolExecutionContext
from src.services import tool_execution
from src.services.case_service import get_case_service
from src.services.tool_execution import _scope

ORG_ID = "018f2f4e-0000-7000-8000-000000000001"


def _ctx(case_id, driver_id="drv-001", roles=frozenset({"driver"})):
    return ToolExecutionContext(
        actor_id=driver_id or "actor-1",
        organization_id=ORG_ID,
        roles=roles,
        case_id=case_id,
        driver_id=driver_id,
        request_id="req-1",
        run_id="run-1",
        tool_call_id="call-1",
        turn_id="turn-1",
    )


def test_prod_settings_db_error_raises_503(monkeypatch):
    """Production + DB raising => 503, never silently falls through."""
    monkeypatch.setattr(tool_execution, "get_settings", lambda: Settings(app_env="production", test_auth_enabled=False))

    def _boom(query, params):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(tool_execution, "_rows", _boom)

    case_id = "018f2f4e-0000-7000-8000-dberrcase001"
    with pytest.raises(HTTPException) as exc_info:
        _scope(_ctx(case_id))
    assert exc_info.value.status_code == 503


def test_prod_settings_no_row_but_in_memory_case_present_raises_404(monkeypatch):
    """Production + no DB row: in-memory fallback must NOT run even if the case
    exists in-memory -> fail closed with 404 (never leaks via fallback)."""
    monkeypatch.setattr(tool_execution, "get_settings", lambda: Settings(app_env="production", test_auth_enabled=False))
    monkeypatch.setattr(tool_execution, "_rows", lambda query, params: [])

    case_id = "018f2f4e-0000-7000-8000-prodnorow0001"
    cs = get_case_service()
    cs._cases[case_id] = {
        "id": case_id,
        "organization_id": ORG_ID,
        "assignment_id": None,
        "assigned_analyst_id": "an-001",
        "driver_id": "drv-001",
        "trip_id": None,
        "vehicle_id": None,
        "status": "active",
    }
    try:
        with pytest.raises(HTTPException) as exc_info:
            _scope(_ctx(case_id))
        assert exc_info.value.status_code == 404
    finally:
        cs._cases.pop(case_id, None)


def test_test_settings_no_row_in_memory_case_owned_by_driver_returns_row(monkeypatch):
    """app_env=="test" and test_auth_enabled: no DB row -> in-memory fallback
    is used and returns the case owned by the requesting driver."""
    monkeypatch.setattr(tool_execution, "get_settings", lambda: Settings(app_env="test", test_auth_enabled=True))
    monkeypatch.setattr(tool_execution, "_rows", lambda query, params: [])

    case_id = "018f2f4e-0000-7000-8000-testfallback1"
    cs = get_case_service()
    cs._cases[case_id] = {
        "id": case_id,
        "organization_id": ORG_ID,
        "assignment_id": "asg-1",
        "assigned_analyst_id": "an-001",
        "driver_id": "drv-001",
        "trip_id": "trip-1",
        "vehicle_id": "veh-1",
        "status": "active",
    }
    try:
        row = _scope(_ctx(case_id, driver_id="drv-001"))
        assert row["id"] == case_id
        assert row["driver_id"] == "drv-001"
    finally:
        cs._cases.pop(case_id, None)
