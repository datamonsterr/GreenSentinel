from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.config import Settings
from src.models.schemas import AdjudicationRequest, CaseActionRequest
from src.services.case_service import (
    CaseService,
    _blocking_guardrail_reasons,
    _is_replaceable_route_snapshot,
    _source_backed_route_geometry,
)

pytestmark = pytest.mark.docker

# Mirrors scripts/generate_synthetic_data.py seed: the "GreenSM Mobility Hanoi Corp"
# organization and its "Le Hoang Nam" fraud analyst.
SEEDED_ORG_ID = "018f2f4e-0000-7000-8000-000000000001"
SEEDED_ANALYST_ID = "018f2f4e-1000-7000-8000-000000000003"


def service(env="test"):
    result = CaseService(Settings(app_env=env, database_url="", _env_file=None))
    result.get_redis_client = lambda: None
    return result


@pytest.mark.asyncio
async def test_deployed_database_unavailable_never_serves_seed():
    svc = service("production")
    assert svc._cases == {}
    with pytest.raises(HTTPException) as error:
        await svc.list_cases()
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_database_query_failure_is_503_not_seed_fallback():
    svc = service("production")
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.execute.side_effect = RuntimeError("unavailable")
    svc._get_db_connection = lambda: conn

    # S4-TENANT deny-by-default: a production caller with no server-supplied org
    # scope is blocked before any query or seed fallback.
    with pytest.raises(HTTPException) as error:
        await svc.list_cases()
    assert error.value.status_code == 403

    # With an explicit tenant, a database query failure surfaces as 503, never seed fallback.
    with pytest.raises(HTTPException) as error:
        await svc.list_cases(organization_id=SEEDED_ORG_ID)
    assert error.value.status_code == 503
    conn.close.assert_called_once()


@pytest.mark.asyncio
async def test_queue_filters_foreign_active_leases_before_pagination():
    svc = service()
    svc._cases = {str(i): {"id": str(i), "status": "ready", "organization_id": "org"} for i in range(4)}
    svc._case_aliases = {}
    svc._active_leases = {
        "0": {"analyst_id": "other", "expires_at": datetime.now(UTC) + timedelta(minutes=1)},
        "1": {"analyst_id": "self", "expires_at": datetime.now(UTC) + timedelta(minutes=1)},
        "2": {"analyst_id": "other", "expires_at": datetime.now(UTC) - timedelta(minutes=1)},
    }
    available = await svc.list_cases(analyst_id="self", organization_id="org", limit=1)
    assert available.total == 3
    assert [case.id for case in available.items] == ["1"]
    locked = await svc.list_cases(analyst_id="self", availability="mine")
    assert {case.id for case in locked.items} == {"1"}
    assert (await svc.list_cases(organization_id="different")).total == 0


def test_conversation_preserves_source_roles_times_and_omits_missing_statements():
    result = CaseService._build_conversation(
        [
            {"role": "driver", "text": "On my way", "occurred_at": "2026-09-25T01:01:00+00:00"},
            {"role": "customer", "text": "Where are you?", "occurred_at": "2026-09-25T01:00:00+00:00"},
            {"role": "driver", "text": "", "occurred_at": None},
        ]
    )
    assert [entry["role"] for entry in result] == ["customer", "driver"]
    assert CaseService._build_conversation([]) == []


def test_case_route_geometry_excludes_synthetic_and_legacy_unprovenanced_lines():
    geometry = {"type": "LineString", "coordinates": [[105.1, 21.1], [105.2, 21.2]]}
    result = _source_backed_route_geometry(
        [
            {
                "id": "real-route",
                "leg": "pickup",
                "provider": "osrm",
                "route": geometry,
                "provenance": {"source": "osrm", "status": "ok"},
            },
            {
                "id": "synthetic-route",
                "leg": "destination",
                "provider": "synthetic-straight-line",
                "route": geometry,
                "provenance": {"origin": "synthetic", "is_shortest_path": False},
            },
            {
                "id": "legacy-route",
                "leg": "destination",
                "provider": "osrm",
                "route": geometry,
                "provenance": {"origin": "osrm"},
            },
        ]
    )

    assert result is not None
    assert list(result) == ["pickup_route"]
    assert result["pickup_route"]["coordinates"] == geometry["coordinates"]
    assert result["pickup_route"]["is_shortest_path"] is False


def test_only_known_seed_routes_are_replaceable():
    assert _is_replaceable_route_snapshot("synthetic-straight-line", {"origin": "synthetic"})
    assert _is_replaceable_route_snapshot("osrm-hanoi", {"origin": "osrm", "profile": "car"})
    assert not _is_replaceable_route_snapshot("osrm", {"origin": "osrm", "profile": "car"})
    assert not _is_replaceable_route_snapshot("osrm-hanoi", {"origin": "osrm", "profile": "driving-car"})
    assert not _is_replaceable_route_snapshot("osrm-hanoi", {"origin": "vendor"})


def test_decision_guardrails_derive_from_recorded_evidence():
    assert _blocking_guardrail_reasons(
        incident_type="app_crash",
        quality_flags='["app_crashed"]',
        telemetry_unavailable=True,
        heavy_congestion=True,
    ) == [
        "platform_incident:app_crash",
        "app_crash_incident",
        "telemetry_unavailable",
        "heavy_congestion_detected",
    ]
    assert _blocking_guardrail_reasons(quality_flags=[]) == []
    assert _blocking_guardrail_reasons(quality_flags=["network_offline"]) == ["telemetry_unavailable"]
    assert _blocking_guardrail_reasons(quality_flags=["invalid_telemetry"]) == ["invalid_telemetry"]
    # Mock location is ERR-05 evidence, never a decision block.
    assert _blocking_guardrail_reasons(quality_flags=["mock_provider_active", "mock_provider_flag"]) == []
    assert _blocking_guardrail_reasons(quality_flags=["position_missing"]) == []


@pytest.mark.asyncio
async def test_v1_rejects_legacy_case_actions_and_adjudication_outcomes():
    svc = service()
    legacy_action = CaseActionRequest.model_construct(action_type="ESCALATE", analyst_id="analyst", notes="legacy")
    legacy_outcome = AdjudicationRequest.model_construct(
        outcome="WARN", analyst_id="analyst", rationale="legacy", expected_case_version=1
    )

    with pytest.raises(HTTPException, match="Only REQUEST_EVIDENCE") as action_error:
        await svc.record_case_action("case", legacy_action)
    assert action_error.value.status_code == 400

    with pytest.raises(HTTPException, match="Only AGREE and DISAGREE") as outcome_error:
        await svc.adjudicate_case("case", legacy_outcome)
    assert outcome_error.value.status_code == 400


@pytest.mark.asyncio
async def test_agree_records_violation_without_sanction():
    svc = service()
    svc._principal_roles[SEEDED_ANALYST_ID] = "analyst"
    svc._cases = {"case": {"id": "case", "version": 1, "assignment_id": "trip", "status": "in_review"}}
    svc._case_aliases = {}
    request = AdjudicationRequest(
        outcome="AGREE",
        analyst_id=SEEDED_ANALYST_ID,
        rationale="Evidence confirms violation",
        expected_case_version=1,
    )
    result = await svc.adjudicate_case("case", request, organization_id=SEEDED_ORG_ID)
    assert result.sanction_applied is None
    assert result.new_version == 2
    assert svc._cases["case"]["status"] == "resolved"


@pytest.mark.asyncio
async def test_evaluation_labels_do_not_change_adjudication_guardrails():
    svc = service()
    svc._principal_roles[SEEDED_ANALYST_ID] = "analyst"
    svc._cases = {"case": {"id": "case", "version": 1, "assignment_id": "trip", "status": "in_review"}}
    svc._case_aliases = {}
    svc._simulation_labels = {"trip": {"expected_guardrail": "app_crash_incident"}}
    request = AdjudicationRequest(
        outcome="AGREE",
        analyst_id=SEEDED_ANALYST_ID,
        rationale="Evidence confirms violation",
        expected_case_version=1,
    )
    result = await svc.adjudicate_case("case", request, organization_id=SEEDED_ORG_ID)
    assert result.sanction_applied is None
    assert result.new_version == 2
