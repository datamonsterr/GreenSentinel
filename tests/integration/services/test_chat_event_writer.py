"""Observable ordering and safe projections of actual invocation callbacks."""

import pytest

from src.services.chat_event_writer import ChatEventWriter


def writer():
    return ChatEventWriter(request_id="request", case_id="case", session_id="session", turn_id="turn")


def test_repeated_tool_names_are_paired_by_unique_call_identity():
    w = writer()
    w.tool_start("lookup", "a")
    w.tool_start("lookup", "b")
    w.tool_end("lookup", "b", status="succeeded", duration_ms=4, summary="Có dữ liệu")
    w.tool_end(
        "lookup",
        "a",
        status="failed",
        duration_ms=6,
        error={"code": "SOURCE_UNAVAILABLE", "message": "Không khả dụng", "retryable": True},
    )
    w.complete()
    assert [e["sequence"] for e in w.events] == list(range(5))
    assert [e["payload"].get("tool_call_id") for e in w.events[:4]] == ["a", "b", "b", "a"]
    assert w.events[-1]["type"] == "run.completed"


def test_interruption_closes_pending_tools_and_has_one_terminal():
    w = writer()
    w.tool_start("lookup", "a")
    w.fail("INTERRUPTED", "Luồng bị gián đoạn", True)
    assert [e["type"] for e in w.events] == ["tool.start", "tool.end", "run.error"]
    assert w.events[1]["payload"]["error"]["code"] == "INTERRUPTED"
    with pytest.raises(ValueError):
        w.emit("text.delta", {"delta": "late"})


def test_completion_cannot_leave_tool_pending():
    w = writer()
    w.tool_start("lookup", "a")
    with pytest.raises(ValueError):
        w.complete()


def test_successful_tool_end_publishes_sanitized_output():
    w = writer()
    output = {"source_type": "first_party_peer_telemetry", "peer_count": 3}
    w.tool_start("fetch_corridor_historical_traffic", "traffic-1")
    w.tool_end(
        "fetch_corridor_historical_traffic",
        "traffic-1",
        status="succeeded",
        duration_ms=4,
        output=output,
    )
    assert w.events[-1]["payload"]["output"] == output


def test_failed_tool_end_never_publishes_output():
    w = writer()
    w.tool_start("query_traffic_incident_feed", "traffic-2")
    w.tool_end(
        "query_traffic_incident_feed",
        "traffic-2",
        status="failed",
        duration_ms=4,
        output={"api_key": "must-not-leak"},
        error={"code": "SOURCE_UNAVAILABLE", "message": "Unavailable", "retryable": True},
    )
    assert "output" not in w.events[-1]["payload"]
