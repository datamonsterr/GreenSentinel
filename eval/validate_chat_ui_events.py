"""Validate the Lead handoff fixtures: python -m eval.validate_chat_ui_events."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs/CHAT_UI_EVENT.schema.json"
FORMATS = FormatChecker()


@FORMATS.checks("date-time")
def valid_timestamp(value: Any) -> bool:
    """Validate calendar dates even without jsonschema's optional format extras."""
    if not isinstance(value, str):
        return True  # The schema's type constraint reports non-string values.
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.tzinfo is not None
    except ValueError:
        return False


def validate_stream(events: list[dict[str, Any]]) -> None:
    """Check event shape plus cross-event invariants for a complete, fresh run."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FORMATS)
    if not events:
        raise ValueError("A complete run cannot be empty")
    identity = (events[0].get("run_id"), events[0].get("message_id"))
    seen: set[str] = set()
    calls: dict[str, str] = {}
    ended: set[str] = set()
    terminal = False
    for sequence, event in enumerate(events):
        validator.validate(event)
        if terminal:
            raise ValueError("Event after terminal event")
        if event["sequence"] != sequence or event["event_id"] in seen:
            raise ValueError("Sequence gap or duplicate event ID")
        seen.add(event["event_id"])
        if (event["run_id"], event["message_id"]) != identity:
            raise ValueError("Run/message identity changed")
        payload = event["payload"]
        if event["type"] == "tool.start":
            call_id = payload["tool_call_id"]
            if call_id in calls:
                raise ValueError("Tool call ID reused")
            calls[call_id] = payload["tool_name"]
        elif event["type"] == "tool.end":
            call_id = payload["tool_call_id"]
            if calls.get(call_id) != payload["tool_name"] or call_id in ended:
                raise ValueError("Tool end has no matching start or was already ended")
            ended.add(call_id)
        elif event["type"] == "routes":
            route_ids = [route["route_id"] for route in payload["routes"]]
            if len(set(route_ids)) != len(route_ids):
                raise ValueError("Duplicate route ID")
            selected = payload["selected_route_id"]
            if selected is not None and selected not in route_ids:
                raise ValueError("Selected route is absent")
        elif event["type"] == "case.list":
            ids = [case["case_id"] for case in payload["items"]]
            if len(set(ids)) != len(ids):
                raise ValueError("Duplicate case ID in page")
            count = payload["total_count"]
            if count is not None and count < len(ids):
                raise ValueError("Total count is smaller than page")
        elif event["type"] in ("run.completed", "run.error"):
            terminal = True
            if event["type"] == "run.completed" and payload["status"] == "completed" and set(calls) != ended:
                raise ValueError("Successful run has unfinished tools")
    if not terminal:
        raise ValueError("Complete fixture has no terminal event")


def main() -> None:
    samples = json.loads((ROOT / "docs/CHAT_UI_EVENT_SAMPLES.json").read_text(encoding="utf-8"))
    for stream in samples["streams"]:
        validate_stream(stream["events"])
        print(f"PASS {stream['name']}: {len(stream['events'])} events")


if __name__ == "__main__":
    main()
