"""Schema and lifecycle rejection tests; no external services required."""

import copy
import json
import unittest

import pytest
from jsonschema.exceptions import ValidationError

from eval.validate_chat_ui_events import ROOT, validate_stream

pytestmark = pytest.mark.docker


class TestChatUiContract(unittest.TestCase):
    def setUp(self) -> None:
        samples = json.loads((ROOT / "docs/CHAT_UI_EVENT_SAMPLES.json").read_text(encoding="utf-8"))
        self.events = samples["streams"][0]["events"]

    def test_all_fixtures(self) -> None:
        samples = json.loads((ROOT / "docs/CHAT_UI_EVENT_SAMPLES.json").read_text(encoding="utf-8"))
        for stream in samples["streams"]:
            with self.subTest(stream=stream["name"]):
                validate_stream(stream["events"])

    def test_rejects_invalid_shapes(self) -> None:
        for field, value in (
            ("timestamp", "2026-02-30T10:00:00.000Z"),
            ("timestamp", "2026-09-24"),
            ("schema_version", "2.0"),
            ("type", "unknown"),
        ):
            events = copy.deepcopy(self.events)
            events[0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                validate_stream(events)
        self.events[0]["payload"]["private_reasoning"] = "must not be rendered"
        with self.assertRaises(ValidationError):
            validate_stream(self.events)

    def test_rejects_unpaired_tool(self) -> None:
        self.events[2]["payload"]["tool_call_id"] = "wrong_call"
        with self.assertRaises(ValueError):
            validate_stream(self.events)

    def test_rejects_sequence_gap(self) -> None:
        self.events[1]["sequence"] = 5
        with self.assertRaises(ValueError):
            validate_stream(self.events)

    def test_rejects_route_errors(self) -> None:
        events = copy.deepcopy(self.events)
        events[7]["payload"]["routes"][0]["geometry"]["coordinates"][0] = [105, 120]
        with self.assertRaises(ValidationError):
            validate_stream(events)
        self.events[7]["payload"]["selected_route_id"] = "absent_route"
        with self.assertRaises(ValueError):
            validate_stream(self.events)

    def test_requires_single_terminal_event(self) -> None:
        with self.assertRaises(ValueError):
            validate_stream(self.events[:-1])
        self.events.append(copy.deepcopy(self.events[-1]))
        with self.assertRaises(ValueError):
            validate_stream(self.events)

    def test_interleaved_tools(self) -> None:
        events = copy.deepcopy(self.events)
        events[2], events[4] = events[4], events[2]
        for index, event in enumerate(events):
            event["sequence"] = index
        validate_stream(events)
