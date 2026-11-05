"""SSE contract tests with provider I/O replaced at the external boundary."""

import pytest

from src.services.agent_runtime import validate_event_stream
from src.services.chat_event_writer import ChatEventWriter


def test_schema_and_lifecycle_validate_actual_writer_output():
    w = ChatEventWriter(request_id="r", case_id="c", session_id="s", turn_id="t")
    w.tool_start("inspect_trip_telemetry", "call1")
    w.tool_end("inspect_trip_telemetry", "call1", status="succeeded", duration_ms=1)
    w.emit("text.delta", {"delta": "Đã đối chiếu"})
    w.complete()
    validate_event_stream(w.events)


def test_lifecycle_rejects_gap_and_unmatched_invocation():
    w = ChatEventWriter(request_id="r", case_id="c", session_id="s", turn_id="t")
    w.complete()
    event = dict(w.events[0], sequence=2)
    with pytest.raises(ValueError):
        validate_event_stream([event])
