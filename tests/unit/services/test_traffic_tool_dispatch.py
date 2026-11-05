from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from src.models.tool_contracts import ToolExecutionContext
from src.services import tool_execution


def context() -> ToolExecutionContext:
    return ToolExecutionContext(
        actor_id="analyst-1",
        organization_id="org-1",
        roles=frozenset({"analyst"}),
        case_id="case-1",
        request_id="request-1",
        run_id="run-1",
        tool_call_id="call-1",
        turn_id="turn-1",
    )


@pytest.mark.asyncio
async def test_dispatch_maps_historical_traffic_to_canonical_result(monkeypatch):
    def scope(_ctx):
        return {"assignment_id": "assignment-1"}

    def rows(query, params):
        if "min(tp.occurred_at)" in query:
            assert params == ("assignment-1",)
            return [
                {
                    "window_start": datetime(2026, 10, 11, 10, 0, tzinfo=UTC),
                    "window_end": datetime(2026, 10, 11, 10, 30, tzinfo=UTC),
                    "west": 105.71,
                    "south": 21.01,
                    "east": 105.79,
                    "north": 21.09,
                }
            ]
        assert "t.organization_id=%s::uuid" in query
        assert "tp.assignment_id<>%s::uuid" in query
        assert "tp.gps_state='valid'" in query
        assert "mock_location_reported" in query
        assert params[0] == "org-1"
        assert params[1] == "assignment-1"
        assert params[2:4] == ("2026-10-11T10:00:00Z", "2026-10-11T10:30:00Z")
        assert params[4:] == (105.71, 21.01, 105.79, 21.09)
        return [
            {"assignment_id": "peer-1", "median_speed_kmh": 15},
            {"assignment_id": "peer-2", "median_speed_kmh": 30},
            {"assignment_id": "peer-3", "median_speed_kmh": 60},
        ]

    async def history(**kwargs):
        assert kwargs["peer_trip_speeds_kmh"] == [15, 30, 60]
        assert kwargs["bbox"] == [105.71, 21.01, 105.79, 21.09]
        assert kwargs["start_time"] == "2026-10-11T10:00:00Z"
        assert kwargs["end_time"] == "2026-10-11T10:30:00Z"
        return {
            "status": "available",
            "source_type": "first_party_peer_telemetry",
            "peer_count": 3,
            "observed_speed_kmh": 30,
            "free_flow_speed_kmh": 60,
            "congestion_ratio": 0.5,
            "congested": True,
            "window_start": "2026-10-11T10:00:00Z",
            "window_end": "2026-10-11T10:30:00Z",
            "method": "median_peer_trip_speed_vs_p85_peer_baseline",
        }

    monkeypatch.setattr(tool_execution, "_scope", scope)
    monkeypatch.setattr(tool_execution, "_rows", rows)
    monkeypatch.setattr("src.services.traffic_evidence_service.fetch_corridor_historical_traffic", history)
    result = await tool_execution.execute_tool(
        "fetch_corridor_historical_traffic",
        {"bbox": [105.7, 21.0, 105.8, 21.1], "start_time": "2026-10-11T10:00:00Z", "end_time": "2026-10-11T10:30:00Z"},
        context(),
    )
    assert result.status == "succeeded"
    assert result.data["congested"] is True
    assert result.provenance[0].kind == "database"


@pytest.mark.asyncio
async def test_dispatch_marks_provider_failure_unavailable(monkeypatch):
    def scope(_ctx):
        return {"assignment_id": "assignment-1"}

    def rows(query, params):
        assert "min(tp.occurred_at)" in query
        assert params == ("assignment-1",)
        return [
            {
                "window_start": datetime(2026, 10, 11, 10, 0, tzinfo=UTC),
                "window_end": datetime(2026, 10, 11, 10, 30, tzinfo=UTC),
                "west": 105.71,
                "south": 21.01,
                "east": 105.79,
                "north": 21.09,
            }
        ]

    async def incidents(**kwargs):
        assert kwargs == {
            "bbox": [105.71, 21.01, 105.79, 21.09],
            "start_time": "2026-10-11T10:00:00Z",
            "end_time": "2026-10-11T10:30:00Z",
        }
        return {
            "status": "unavailable",
            "reason": "provider_unreachable",
            "historical_absence_proven": False,
            "retention": "memory_only",
        }

    monkeypatch.setattr(tool_execution, "_scope", scope)
    monkeypatch.setattr(tool_execution, "_rows", rows)
    monkeypatch.setattr("src.services.traffic_evidence_service.query_traffic_incident_feed", incidents)
    result = await tool_execution.execute_tool(
        "query_traffic_incident_feed",
        {"bbox": [105.7, 21.0, 105.8, 21.1], "start_time": "2026-10-11T10:00:00Z", "end_time": "2026-10-11T10:30:00Z"},
        context(),
    )
    assert result.status == "succeeded"
    assert result.data == {
        "status": "unavailable",
        "reason": "provider_unreachable",
        "historical_absence_proven": False,
        "retention": "memory_only",
    }
    assert result.provenance[0].kind == "unavailable"


@pytest.mark.asyncio
async def test_driver_cannot_dispatch_another_case(monkeypatch):
    def scope(_ctx):
        raise HTTPException(403, "Driver does not own case")

    called = False

    async def provider(**_kwargs):
        nonlocal called
        called = True
        return {"status": "available"}

    monkeypatch.setattr(tool_execution, "_scope", scope)
    monkeypatch.setattr("src.services.traffic_evidence_service.query_traffic_incident_feed", provider)
    driver_context = context().model_copy(update={"roles": frozenset({"driver"}), "driver_id": "driver-1"})
    result = await tool_execution.execute_tool(
        "query_traffic_incident_feed",
        {
            "case_id": "case-2",
            "bbox": [105.7, 21.0, 105.8, 21.1],
            "start_time": "2026-10-11T10:00:00Z",
            "end_time": "2026-10-11T10:30:00Z",
        },
        driver_context,
    )
    assert result.status == "failed"
    assert result.error.code == "FORBIDDEN"
    assert called is False


@pytest.mark.asyncio
async def test_driver_case_id_mismatch_is_injected_from_context_not_rejected(monkeypatch):
    """R3: tools needing a case id must get it injected from the trusted runtime
    context when the model omits it or passes a wrong one, instead of erroring.
    """
    captured = {}

    async def dispatch(_tool, args, _ctx, _scope):
        captured["args"] = dict(args)
        return {
            "case_id": args.get("case_id"),
            "points": [],
            "summary": {},
            "total_samples": 0,
            "sampled_from_samples": 0,
            "returned_samples": 0,
            "truncated": False,
            "sampling": "none",
        }, []

    monkeypatch.setattr(tool_execution, "_scope", lambda _ctx: {"assignment_id": "assignment-1"})
    monkeypatch.setattr(tool_execution, "_dispatch", dispatch)
    driver_context = context().model_copy(update={"roles": frozenset({"driver"}), "driver_id": "driver-1"})

    result = await tool_execution.execute_tool(
        "inspect_trip_telemetry",
        {"case_id": "case-WRONG-HALLUCINATED"},
        driver_context,
    )

    assert result.status == "succeeded", result.model_dump()
    assert captured["args"]["case_id"] == "case-1"


@pytest.mark.asyncio
async def test_dispatch_emits_canonical_start_and_end(monkeypatch):
    async def history(**_kwargs):
        return _available_history()

    monkeypatch.setattr(tool_execution, "_scope", lambda _ctx: {"assignment_id": "assignment-1"})

    async def traffic_scope(_assignment_id, args):
        return args

    monkeypatch.setattr(tool_execution, "_case_traffic_scope", traffic_scope)
    monkeypatch.setattr(
        tool_execution,
        "_rows",
        lambda _query, _params: [
            {"assignment_id": "peer-1", "median_speed_kmh": 20},
            {"assignment_id": "peer-2", "median_speed_kmh": 30},
            {"assignment_id": "peer-3", "median_speed_kmh": 60},
        ],
    )
    monkeypatch.setattr(
        "src.services.traffic_evidence_service.fetch_corridor_historical_traffic",
        history,
    )
    events = []
    result = await tool_execution.execute_tool(
        "fetch_corridor_historical_traffic",
        {"bbox": [105.7, 21.0, 105.8, 21.1], "start_time": "2026-10-11T10:00:00Z", "end_time": "2026-10-11T10:30:00Z"},
        context(),
        on_event=events.append,
    )
    assert result.status == "succeeded"
    assert [(event["type"], event["tool_id"]) for event in events] == [
        ("tool_start", "fetch_corridor_historical_traffic"),
        ("tool_end", "fetch_corridor_historical_traffic"),
    ]
    assert events[-1]["output"] == _available_history()
    assert "api_key" not in events[-1]["output"]


@pytest.mark.asyncio
async def test_fraud_analyst_dispatches_traffic_tool_and_emits_events(monkeypatch):
    monkeypatch.setattr(tool_execution, "_scope", lambda _ctx: {"assignment_id": "assignment-1"})
    monkeypatch.setattr(tool_execution, "_dispatch", lambda *_args, **_kwargs: _async_result(_available_history()))
    events = []
    fraud_analyst_context = context().model_copy(update={"roles": frozenset({"fraud_analyst"})})

    result = await tool_execution.execute_tool(
        "fetch_corridor_historical_traffic",
        {
            "bbox": [105.7, 21.0, 105.8, 21.1],
            "start_time": "2026-10-11T10:00:00Z",
            "end_time": "2026-10-11T10:30:00Z",
        },
        fraud_analyst_context,
        on_event=events.append,
    )

    assert result.status == "succeeded"
    assert [event["type"] for event in events] == ["tool_start", "tool_end"]


@pytest.mark.asyncio
async def test_case_scoped_traffic_tool_infers_arguments_and_emits_events(monkeypatch):
    monkeypatch.setattr(tool_execution, "_scope", lambda _ctx: {"assignment_id": "assignment-1"})
    monkeypatch.setattr(tool_execution, "_dispatch", lambda *_args, **_kwargs: _async_result(_available_history()))
    events = []

    result = await tool_execution.execute_tool(
        "fetch_corridor_historical_traffic",
        {},
        context(),
        on_event=events.append,
    )

    assert result.status == "succeeded"
    assert [event["type"] for event in events] == ["tool_start", "tool_end"]


@pytest.mark.asyncio
async def test_missing_case_telemetry_and_incomplete_override_returns_validation_error(monkeypatch):
    monkeypatch.setattr(tool_execution, "_scope", lambda _ctx: {"assignment_id": "assignment-1"})
    monkeypatch.setattr(tool_execution, "_rows", lambda *_args, **_kwargs: [])
    events = []

    result = await tool_execution.execute_tool(
        "fetch_corridor_historical_traffic",
        {},
        context(),
        on_event=events.append,
    )

    assert result.status == "failed"
    assert result.error.code == "VALIDATION_ERROR"
    assert [event["type"] for event in events] == ["tool_start", "tool_end"]


async def _async_result(value):
    return value, []


def _available_history():
    return {
        "status": "available",
        "source_type": "first_party_peer_telemetry",
        "peer_count": 3,
        "observed_speed_kmh": 30,
        "free_flow_speed_kmh": 60,
        "congestion_ratio": 0.5,
        "congested": True,
        "window_start": "2026-10-11T10:00:00Z",
        "window_end": "2026-10-11T10:30:00Z",
        "method": "median_peer_trip_speed_vs_p85_peer_baseline",
    }


def test_incident_public_output_excludes_raw_provider_data():
    output = tool_execution._public_tool_output(
        "query_traffic_incident_feed",
        {
            "status": "available",
            "incidents": [{"description": "raw provider detail", "api_key": "secret"}],
            "congested": True,
            "observed_at": "2026-10-11T10:15:00Z",
            "historical_absence_proven": False,
            "retention": "memory_only",
            "headers": {"Authorization": "secret"},
        },
    )

    assert output == {
        "status": "available",
        "congested": True,
        "observed_at": "2026-10-11T10:15:00Z",
        "historical_absence_proven": False,
        "retention": "memory_only",
        "incident_count": 1,
    }


def test_incident_unavailable_output_keeps_unknown_explicit_without_fake_zero_count():
    output = tool_execution._public_tool_output(
        "query_traffic_incident_feed",
        {
            "status": "unavailable",
            "reason": "provider_not_configured",
            "historical_absence_proven": False,
            "retention": "memory_only",
        },
    )

    assert output == {
        "status": "unavailable",
        "reason": "provider_not_configured",
        "historical_absence_proven": False,
        "retention": "memory_only",
    }
