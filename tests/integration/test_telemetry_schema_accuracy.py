"""A GPS archive can report a position without reporting its accuracy."""

import json
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from src.models.schemas import TelemetryEventEnvelope
from tests.support.repo import REPO_ROOT

pytestmark = pytest.mark.docker

SCHEMA_PATH = REPO_ROOT / "docs/architecture/schemas/telemetry-event.schema.json"


def _event(accuracy: float | None) -> dict:
    return {
        "schema_version": 1,
        "event_id": str(uuid4()),
        "event_type": "telemetry.observed",
        "source": "porto-taxi",
        "occurred_at": "2013-07-01T00:00:00Z",
        "correlation_id": str(uuid4()),
        "trip_id": str(uuid4()),
        "assignment_id": str(uuid4()),
        "driver_id": str(uuid4()),
        "sequence": 0,
        "payload": {
            "position": {"latitude": 41.15, "longitude": -8.61, "accuracy_m": accuracy},
            "app_state": "unknown",
            "network_state": "unknown",
            "gps_state": "unknown",
            "mock_location_reported": None,
        },
    }


@pytest.mark.parametrize("accuracy", [None, 0.0, 8.5])
def test_unknown_or_measured_accuracy_matches_both_contracts(accuracy):
    event = _event(accuracy)
    schema = json.loads(SCHEMA_PATH.read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(event)
    parsed = TelemetryEventEnvelope.model_validate(event)
    assert parsed.payload.position.accuracy_m == accuracy


def test_negative_accuracy_rejected_by_both_contracts():
    event = _event(-1.0)
    schema = json.loads(SCHEMA_PATH.read_text())
    assert list(Draft202012Validator(schema).iter_errors(event))
    with pytest.raises(ValidationError):
        TelemetryEventEnvelope.model_validate(event)
