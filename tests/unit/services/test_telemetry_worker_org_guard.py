"""S4-TENANT #294 P1b: DEFAULT_ORG_ID writes are sim/test-scoped, fail closed."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.config import Settings
from src.services import telemetry_queue_worker as worker


def _production_settings(**kwargs):
    return Settings(app_env="production", database_url="", clerk_secret_key="sk_test_unit", **kwargs)


def test_default_org_write_refused_in_production():
    with pytest.raises(HTTPException) as exc_info:
        worker._require_simulation_tenant_writes(_production_settings())
    assert exc_info.value.status_code == 403


def test_default_org_write_allowed_on_test_stack():
    worker._require_simulation_tenant_writes(Settings(app_env="test", test_auth_enabled=True))


def test_default_org_write_allowed_with_explicit_simulation_opt_in(monkeypatch):
    monkeypatch.setenv("SIMULATION_TENANT_ALLOW", "1")
    worker._require_simulation_tenant_writes(_production_settings())


def test_default_org_write_refused_when_opt_in_absent(monkeypatch):
    monkeypatch.delenv("SIMULATION_TENANT_ALLOW", raising=False)
    with pytest.raises(HTTPException):
        worker._require_simulation_tenant_writes(_production_settings())


def test_simulation_flag_kwarg_removed_fail_closed(monkeypatch):
    """No caller flag can enable DEFAULT_ORG writes; only tenant scope can.

    Regression for 5d7dcbe: payload is_simulation/force_create_case must
    never substitute for APP_ENV=test+test_auth or SIMULATION_TENANT_ALLOW=1.
    """
    monkeypatch.delenv("SIMULATION_TENANT_ALLOW", raising=False)
    with pytest.raises(TypeError):
        worker._require_simulation_tenant_writes(_production_settings(), allow_simulation=True)  # type: ignore[call-arg]
    with pytest.raises(HTTPException):
        worker._require_simulation_tenant_writes(_production_settings())


def test_persist_nominal_event_refuses_production(monkeypatch):
    monkeypatch.setattr(worker, "get_settings", lambda: _production_settings())
    monkeypatch.delenv("SIMULATION_TENANT_ALLOW", raising=False)
    with pytest.raises(HTTPException) as exc_info:
        worker._persist_nominal_event(
            object(),
            trip_id="t",
            assignment_id="a",
            driver_id="d",
            points=[],
            event_data={},
            now=__import__("datetime").datetime.now(__import__("datetime").UTC),
        )
    assert exc_info.value.status_code == 403


async def test_process_telemetry_event_refuses_default_org_write_in_production(monkeypatch):
    """A production run with a live DB must not commingle into DEFAULT_ORG_ID."""
    from src.services.case_service import CaseService

    service = CaseService(settings=_production_settings())
    monkeypatch.delenv("SIMULATION_TENANT_ALLOW", raising=False)

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query, params=None):
            raise AssertionError("denied write reached the database")

        def fetchone(self):
            return None

    class Conn:
        def cursor(self):
            return Cursor()

        def close(self):
            pass

    monkeypatch.setattr(service, "_get_db_connection", lambda: Conn())
    monkeypatch.setattr(
        worker.JevAssessmentAgent,
        "assess",
        AsyncMock(
            return_value={
                "category": "ERR-02",
                "priority_tier": 1,
                "priority_score": 80,
                "confidence": 0.92,
                "reason_codes": ["ERR-02"],
                "forensic_brief": "brief",
            }
        ),
    )
    with pytest.raises(HTTPException) as exc_info:
        await worker.process_telemetry_event(
            {"trip_id": "t", "driver_id": "d", "points": []},
            service,
        )
    assert exc_info.value.status_code == 403
