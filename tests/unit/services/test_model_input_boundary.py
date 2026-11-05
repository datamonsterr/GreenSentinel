"""Label-isolation boundary tests for model input projection.

TDD contract (issue #63 T2):
- Same observed evidence + different evaluation labels → identical deterministic result
- LLM prompt must not contain evaluation label keys
- Guardrail short-circuit is unaffected by projection
- Saved feature_sets/dossier must not contain evaluation label keys
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.services.case_service import get_case_service
from src.services.model_input_projection import project_model_input
from src.services.telemetry_queue_worker import JevAssessmentAgent, process_telemetry_event

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_POINT_STALL = {
    "latitude": 21.0285,
    "longitude": 105.8542,
    "speed_mps": 0.0,
    "bearing_deg": 0.0,
    "accuracy_m": 4.0,
    "app_state": "foreground",
    "network_state": "online",
    "gps_state": "valid",
    "mock_location_reported": False,
}

_POINT_MOCK = {
    "latitude": 21.0285,
    "longitude": 105.8542,
    "speed_mps": 5.0,
    "bearing_deg": 90.0,
    "accuracy_m": 10.0,
    "app_state": "foreground",
    "network_state": "online",
    "gps_state": "mock_reported",
    "mock_location_reported": True,
}

_EVAL_LABEL_KEYS = {
    "scenario",
    "expected_category",
    "expected_guardrail",
    "expected_outcome",
    "intent",
    "simulation_id",
    "expected_guardrail_reason",
}


def _base_event(points: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    from uuid import uuid4

    return {
        "trip_id": str(uuid4()),
        "assignment_id": str(uuid4()),
        "driver_id": "018f2f4e-3000-7000-8000-000000000099",
        "points": points,
        **extra,
    }


# ---------------------------------------------------------------------------
# T1: Same evidence, different labels → identical deterministic result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_label_isolation_same_evidence_different_labels_identical_result() -> None:
    """Same observed telemetry evidence + different evaluation labels → identical classification.

    A stall trip (stationary_duration_s=210, speed=0) with 'scenario=driver_stall_cancel'
    must produce the same result as the same trip with 'scenario=phantom_booking' or
    no scenario at all.  The classifier must key on evidence, not on the label.
    """
    agent = JevAssessmentAgent()

    evidence_base = {
        "stationary_duration_s": 210,
        "lifecycle_state": "cancelled",
        "cancellation_reason": "driver_stalled_too_long",
        "cancellation_actor": "driver",
        "points": [_POINT_STALL],
    }

    # Same evidence, three different label assignments
    result_stall_label = await agent.assess({**evidence_base, "scenario": "driver_stall_cancel"})
    result_phantom_label = await agent.assess({**evidence_base, "scenario": "phantom_booking"})
    result_no_label = await agent.assess({**evidence_base})

    # All three must agree on category because evidence is identical
    assert result_stall_label["category"] == result_phantom_label["category"], (
        f"Label contamination: 'driver_stall_cancel' → {result_stall_label['category']} but "
        f"'phantom_booking' → {result_phantom_label['category']} on identical evidence"
    )
    assert result_stall_label["category"] == result_no_label["category"], (
        f"Label contamination: labeled → {result_stall_label['category']} but "
        f"unlabeled → {result_no_label['category']} on identical evidence"
    )


# ---------------------------------------------------------------------------
# T2: Phantom/collusion scenario label alone must NOT yield ERR-04
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_phantom_label_without_evidence_no_err04() -> None:
    """'scenario=phantom_booking' alone (no circular route / fingerprint evidence) must NOT
    produce ERR-04.  Phantom/collusion labels without observable evidence must not
    determine assessment.
    """
    agent = JevAssessmentAgent()

    # Normal-looking telemetry with phantom label
    result = await agent.assess(
        {
            "scenario": "phantom_booking",
            "points": [
                {
                    "latitude": 21.0285,
                    "longitude": 105.8542,
                    "speed_mps": 8.5,
                    "app_state": "foreground",
                    "network_state": "online",
                    "gps_state": "valid",
                    "mock_location_reported": False,
                }
            ],
        }
    )
    assert result["category"] != "ERR-04", (
        f"phantom_booking label without observable evidence yielded ERR-04 "
        f"(confidence={result.get('confidence')}).  Labels must not determine assessment."
    )


# ---------------------------------------------------------------------------
# T3: LLM prompt must not contain evaluation label keys
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_prompt_excludes_evaluation_labels() -> None:
    """The prompt passed to the LLM must not mention evaluation label keys.

    We capture the string sent to `model.ainvoke` and assert none of the
    label keys appear verbatim.
    """
    from unittest.mock import MagicMock, patch

    captured_prompts: list[str] = []

    async def fake_ainvoke(messages: Any) -> Any:
        for role, content in messages:
            captured_prompts.append(content)
        msg = MagicMock()
        msg.content = '{"category":"no_violation","priority_tier":2,"priority_score":15,"confidence":0.95,"reason_codes":[],"forensic_brief":"ok"}'
        return msg

    mock_model = MagicMock()
    mock_model.ainvoke = fake_ainvoke

    agent = JevAssessmentAgent()

    with patch("src.agents.graph.get_chat_model", return_value=mock_model):
        agent.settings.openrouter_api_key = "fake-key"
        await agent.assess(
            event_data={
                "scenario": "phantom_booking",
                "expected_category": "ERR-04",
                "intent": "test_collusion",
                "simulation_id": "sim-001",
                "points": [_POINT_STALL],
            },
            use_llm=True,
        )

    assert captured_prompts, "No prompt was captured — LLM path not exercised"
    full_prompt = " ".join(captured_prompts)

    for key in ("scenario=", "expected_category", "expected_outcome", "simulation_id", "intent"):
        assert key not in full_prompt, (
            f"Evaluation label key '{key}' found in LLM prompt.  Labels must be stripped before model input."
        )


# ---------------------------------------------------------------------------
# T4: Guardrail short-circuit unaffected by projection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guardrail_short_circuit_unaffected_by_projection() -> None:
    """APP_CRASH guardrail must still block classification regardless of projection.

    A crashed-app trip should produce 'insufficient_evidence' even after projection
    strips the scenario label.  DB is mocked out (unit seam — no real DB needed).
    """
    from unittest.mock import patch

    service = get_case_service()
    driver_id = "018f2f4e-3000-7000-8000-000000000098"
    service.set_driver_status(driver_id, "active")

    event = _base_event(
        points=[
            {
                "latitude": 21.0285,
                "longitude": 105.8542,
                "speed_mps": 0.0,
                "app_state": "crashed",
                "network_state": "online",
                "gps_state": "valid",
                "mock_location_reported": False,
            }
        ],
        driver_id=driver_id,
        stationary_duration_s=210,
        scenario="driver_stall_cancel",  # label that would normally produce ERR-02
        expected_category="ERR-02",
        expected_guardrail="APP_CRASH",
    )

    # Unit seam: no real DB; _get_db_connection returns None
    with patch.object(service, "_get_db_connection", return_value=None):
        result = await process_telemetry_event(event, case_service=service)

    assert result["assessment"]["category"] == "insufficient_evidence", (
        f"Expected guardrail to short-circuit to insufficient_evidence, got {result['assessment']['category']}"
    )
    assert result["assessment"]["guardrail"]["reason"] == "APP_CRASH"


# ---------------------------------------------------------------------------
# T5: project_model_input strips all evaluation label keys
# ---------------------------------------------------------------------------


def test_project_model_input_strips_label_keys() -> None:
    """project_model_input must remove all evaluation label keys from the event."""
    dirty = {
        "trip_id": "t1",
        "driver_id": "d1",
        "scenario": "phantom_booking",
        "expected_category": "ERR-04",
        "expected_guardrail": "APP_CRASH",
        "expected_outcome": "SUSPEND",
        "intent": "test_collusion",
        "simulation_id": "sim-042",
        "stationary_duration_s": 210,
        "points": [
            {
                **_POINT_STALL,
                "expected_category": "ERR-04",  # nested label in a point
            }
        ],
    }
    clean = project_model_input(dirty)

    for key in _EVAL_LABEL_KEYS:
        assert key not in clean, f"Evaluation key '{key}' survived projection in top-level"

    for pt in clean.get("points", []):
        for key in _EVAL_LABEL_KEYS:
            assert key not in pt, f"Evaluation key '{key}' survived projection in nested point"

    # Operational keys must survive
    assert clean["trip_id"] == "t1"
    assert clean["stationary_duration_s"] == 210
    assert len(clean["points"]) == 1
    assert clean["points"][0]["speed_mps"] == 0.0


def test_project_model_input_deeply_allowlists_observations_and_does_not_mutate() -> None:
    """Nested geometry, incidents, and traffic observations cannot carry labels by reference."""
    event = {
        "points": [
            {
                "position": {
                    "type": "Point",
                    "coordinates": [105.85, 21.03],
                    "scenario": "spoofed",
                },
                "latitude": 21.03,
                "longitude": 105.85,
                "accuracy_m": 4,
                "nested": {"intent": "leak"},
            }
        ],
        "pickup": {"type": "Point", "coordinates": [105.84, 21.02], "intent": "leak"},
        "incidents": [
            {
                "incident_type": "network_loss",
                "start": "2026-10-01T00:00:00Z",
                "end": "2026-10-01T00:01:00Z",
                "state": "resolved",
                "expected_outcome": "SUSPEND",
            }
        ],
        "traffic_observations": [
            {
                "observed_at": "2026-10-01T00:00:00Z",
                "valid_until": "2026-10-01T00:05:00Z",
                "speed": 12,
                "congestion": "moderate",
                "source": "provider",
                "is_simulated": False,
                "intent": "leak",
            }
        ],
    }
    before = json.loads(json.dumps(event))

    clean = project_model_input(event)

    assert event == before
    assert clean["points"] is not event["points"]
    assert clean["points"][0]["position"] is not event["points"][0]["position"]
    assert clean["points"][0]["position"]["coordinates"] is not event["points"][0]["position"]["coordinates"]
    assert clean["incidents"] is not event["incidents"]
    assert clean["traffic_observations"] is not event["traffic_observations"]
    assert clean["points"][0]["position"] == {"type": "Point", "coordinates": [105.85, 21.03]}
    assert clean["pickup"] == {"type": "Point", "coordinates": [105.84, 21.02]}
    assert clean["incidents"] == [
        {
            "incident_type": "network_loss",
            "start": "2026-10-01T00:00:00Z",
            "end": "2026-10-01T00:01:00Z",
            "state": "resolved",
        }
    ]
    assert clean["traffic_observations"] == [
        {
            "observed_at": "2026-10-01T00:00:00Z",
            "valid_until": "2026-10-01T00:05:00Z",
            "speed": 12,
            "congestion": "moderate",
            "source": "provider",
            "is_simulated": False,
        }
    ]


def test_project_model_input_relabeling_nested_observed_evidence_is_invariant() -> None:
    """Changing nested evaluation labels cannot change the projected observed evidence."""
    observed = {
        "points": [{"position": {"type": "Point", "coordinates": [105.85, 21.03]}}],
        "incidents": [{"incident_type": "app_crash", "state": "open"}],
        "traffic_observations": [{"speed": 8, "source": "provider"}],
    }
    relabeled = json.loads(json.dumps(observed))
    relabeled["points"][0]["position"]["scenario"] = "other"
    relabeled["incidents"][0]["expected_category"] = "ERR-05"
    relabeled["traffic_observations"][0]["intent"] = "test"

    assert project_model_input(observed) == project_model_input(relabeled)


def test_project_model_input_retains_real_incident_traffic_and_position_shapes() -> None:
    event = {
        "points": [
            {
                "position": {"latitude": 21.03, "longitude": 105.85, "accuracy_m": 4.0, "intent": "bad"},
            }
        ],
        "incidents": [
            {
                "incident_id": "inc-1",
                "incident_type": "app_crash",
                "state": "open",
                "started_at": "2026-10-01T00:00:00Z",
                "ended_at": None,
                "source_event_id": "evt-1",
                "expected_category": "ERR-05",
            }
        ],
        "traffic_observations": [
            {
                "observed_at": "2026-10-01T00:00:00Z",
                "valid_until": "2026-10-01T00:05:00Z",
                "average_speed_mps": 4.2,
                "congestion_level": "heavy",
                "provenance": {"origin": "sensor", "intent": "bad"},
                "scenario": "bad",
            }
        ],
    }

    clean = project_model_input(event)

    assert clean["points"][0]["position"] == {
        "latitude": 21.03,
        "longitude": 105.85,
        "accuracy_m": 4.0,
    }
    assert clean["incidents"][0] == {
        "incident_id": "inc-1",
        "incident_type": "app_crash",
        "state": "open",
        "started_at": "2026-10-01T00:00:00Z",
        "ended_at": None,
        "source_event_id": "evt-1",
    }
    assert clean["traffic_observations"][0] == {
        "observed_at": "2026-10-01T00:00:00Z",
        "valid_until": "2026-10-01T00:05:00Z",
        "average_speed_mps": 4.2,
        "congestion_level": "heavy",
        "provenance": {"origin": "sensor"},
    }


def test_project_model_input_drops_malicious_coordinate_and_nested_values() -> None:
    event = {
        "points": [
            {
                "position": {
                    "type": "Point",
                    "coordinates": [105.85, {"longitude": 21.03, "expected_outcome": "SUSPEND"}],
                },
            }
        ],
        "incidents": [{"incident_type": {"intent": "bad"}, "state": ["open"]}],
        "traffic_observations": [{"average_speed_mps": {"intent": "bad"}, "provenance": ["bad"]}],
    }

    clean = project_model_input(event)

    assert clean["points"][0]["position"] == {"type": "Point"}
    assert clean["incidents"][0] == {}
    assert clean["traffic_observations"][0] == {}


@pytest.mark.parametrize(
    ("coordinates", "expected"),
    [
        ([105.85, {"longitude": 21.03}], {}),
        ([105.85, float("nan")], {}),
        ([105.85, float("inf")], {}),
        ([105.85, 21.03], [105.85, 21.03]),
    ],
)
def test_project_model_input_sanitizes_list_form_route_geometry(coordinates: list[object], expected: Any) -> None:
    event = {"pickup": coordinates}

    clean = project_model_input(event)

    assert clean["pickup"] == expected


# ---------------------------------------------------------------------------
# T6: Saved features/dossier must not contain evaluation labels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_event_features_no_label_leak() -> None:
    """process_telemetry_event must not store evaluation label keys in model_assessments.

    DB is mocked out (unit seam); we check in-memory _model_assessments only.
    """
    from unittest.mock import patch

    service = get_case_service()
    driver_id = "018f2f4e-3000-7000-8000-000000000097"
    service.set_driver_status(driver_id, "active")

    event = _base_event(
        points=[_POINT_STALL],
        driver_id=driver_id,
        stationary_duration_s=210,
        lifecycle_state="cancelled",
        cancellation_reason="driver_stalled_too_long",
        scenario="driver_stall_cancel",
        expected_category="ERR-02",
        simulation_id="sim-099",
    )

    with patch.object(service, "_get_db_connection", return_value=None):
        result = await process_telemetry_event(event, case_service=service)

    case_id = result.get("case_id")

    # Check model_assessments stored in service
    if case_id:
        stored = service._model_assessments.get(case_id, {})
        stored_str = json.dumps(stored)
        for key in _EVAL_LABEL_KEYS:
            assert key not in stored_str, f"Evaluation key '{key}' found in stored model assessment: {stored_str[:200]}"


@pytest.mark.asyncio
async def test_db_write_features_and_dossier_no_label_leak() -> None:
    """When writing to DB, evidence_snapshots dossier and feature_sets features must not contain eval labels."""
    from unittest.mock import MagicMock, patch

    service = get_case_service()
    driver_id = "018f2f4e-3000-7000-8000-000000000096"
    service.set_driver_status(driver_id, "active")

    event = _base_event(
        points=[_POINT_STALL],
        driver_id=driver_id,
        stationary_duration_s=210,
        lifecycle_state="cancelled",
        cancellation_reason="driver_stalled_too_long",
        scenario="driver_stall_cancel",
        expected_category="ERR-02",
        simulation_id="sim-100",
    )

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchone.return_value = None

    executed_queries: list[tuple[str, Any]] = []

    def fake_execute(query: str, params: Any = None) -> None:
        executed_queries.append((query, params))
        mock_cursor.fetchone.return_value = {"event_id": params[0]} if "RETURNING event_id" in query else None

    mock_cursor.execute = fake_execute

    with patch.object(service, "_get_db_connection", return_value=mock_conn):
        await process_telemetry_event(event, case_service=service)

    assert executed_queries, "No queries were executed against DB"
    for _query, params in executed_queries:
        if params:
            for p in params:
                if isinstance(p, str) and (p.startswith("{") or p.startswith("[")):
                    for key in _EVAL_LABEL_KEYS:
                        assert key not in p, f"Evaluation label key '{key}' leaked into DB payload: {p}"
