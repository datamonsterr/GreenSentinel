from hashlib import sha256

import psycopg
import pytest

import scripts.gis_test_setup as gis_test_setup
from scripts.gis_test_setup import (
    database_fingerprint,
    filter_case_dependents,
    gis_schema_ready,
    parse_health_response,
    scenario_lifecycle_values,
    validate_database_url,
    validate_local_redis_url,
    validate_local_service_url,
)


def test_parse_health_response_requires_connected_database():
    assert parse_health_response('{"status":"ok","database":"connected"}') is True
    assert parse_health_response('{"status":"ok","database":"disconnected"}') is False


@pytest.mark.parametrize("payload", ["", "not-json", '{"status":"ok"}', "[]"])
def test_parse_health_response_rejects_non_ready_payloads(payload):
    assert parse_health_response(payload) is False


def test_validate_local_service_url_rejects_foreign_service():
    with pytest.raises(ValueError, match="loopback"):
        validate_local_service_url("http://qdrant.example.test:6333")


def test_validate_local_service_url_accepts_explicit_local_qdrant():
    assert validate_local_service_url("http://127.0.0.1:6333", "QDRANT_URL")


@pytest.mark.parametrize(
    "url",
    [None, "sqlite:///issue61_test", "postgresql://example.test/issue61_test", "postgresql://127.0.0.1/postgres"],
)
def test_validate_database_url_rejects_unsafe_or_non_issue61_targets(url):
    with pytest.raises(ValueError):
        validate_database_url(url)


def test_validate_database_url_accepts_loopback_issue61_database():
    assert validate_database_url("postgresql://127.0.0.1/issue61_test")


def test_validate_local_redis_url_checks_parsed_hostname():
    assert validate_local_redis_url("redis://127.0.0.1:16379/1")
    with pytest.raises(ValueError, match="loopback"):
        validate_local_redis_url("redis://localhost:123@remote.example/1")


def test_scenario_lifecycle_values_preserve_fixture_state():
    assert scenario_lifecycle_values({"status": "in_progress"}, {"state": "accepted"}, {"status": "review"}) == (
        "in_progress",
        "accepted",
        "review",
    )


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return self.rows


class _ControlledConnection:
    def __init__(self, results):
        self.results = iter(results)
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.queries.append((str(query), params))
        result = next(self.results)
        if isinstance(result, BaseException):
            raise result
        return _Result(result)


def test_gis_schema_ready_returns_true_for_complete_schema(monkeypatch):
    connection = _ControlledConnection(
        [
            [("app.fraud_cases",)],
            [],
            [],
            [],
            [],
        ]
    )
    monkeypatch.setattr(gis_test_setup.psycopg, "connect", lambda url: connection)

    assert gis_schema_ready("postgresql://127.0.0.1/issue61_test") is True


def test_gis_schema_ready_returns_false_for_empty_database(monkeypatch):
    connection = _ControlledConnection([[(None,)]])
    monkeypatch.setattr(gis_test_setup.psycopg, "connect", lambda url: connection)

    assert gis_schema_ready("postgresql://127.0.0.1/issue61_empty") is False


def test_gis_schema_ready_returns_false_for_incomplete_database(monkeypatch):
    connection = _ControlledConnection([[("app.fraud_cases",)], psycopg.errors.UndefinedColumn("missing column")])
    monkeypatch.setattr(gis_test_setup.psycopg, "connect", lambda url: connection)

    assert gis_schema_ready("postgresql://127.0.0.1/issue61_partial") is False


def test_database_fingerprint_identifies_tables_counts_and_content_changes(monkeypatch):
    def connection(table_rows):
        return _ControlledConnection([[("trips",), ("telemetry_points",)], *([row] for row in table_rows)])

    connections = iter(
        [
            connection([(2, "abc"), (4, "def")]),
            connection([(3, "abc"), (4, "def")]),
            connection([(2, "xyz"), (4, "def")]),
        ]
    )
    monkeypatch.setattr(gis_test_setup.psycopg, "connect", lambda url: next(connections))

    baseline = database_fingerprint("postgresql://127.0.0.1/issue61_test")
    changed_count = database_fingerprint("postgresql://127.0.0.1/issue61_test")
    changed_content = database_fingerprint("postgresql://127.0.0.1/issue61_test")

    assert baseline == {
        "trips": (2, sha256(b"abc").hexdigest()),
        "telemetry_points": (4, sha256(b"def").hexdigest()),
    }
    assert changed_count["trips"][0] != baseline["trips"][0]
    assert changed_count["trips"][1] == baseline["trips"][1]
    assert changed_content["trips"][0] == baseline["trips"][0]
    assert changed_content["trips"][1] != baseline["trips"][1]
    assert set(baseline) == {"trips", "telemetry_points"}


def test_filter_case_dependents_retains_complete_chain_and_removes_omitted_chain():
    data = {
        "fraud_cases": [{"id": "case-keep"}],
        "case_assignment_history": [
            {"id": "history-keep", "case_id": "case-keep"},
            {"id": "history-drop", "case_id": "case-drop"},
        ],
        "review_leases": [{"id": "lease-keep", "case_id": "case-keep"}, {"id": "lease-drop", "case_id": "case-drop"}],
        "driver_submissions": [
            {"id": "submission-keep", "case_id": "case-keep"},
            {"id": "submission-drop", "case_id": "case-drop"},
        ],
        "evidence_snapshots": [
            {"id": "evidence-keep", "case_id": "case-keep"},
            {"id": "evidence-drop", "case_id": "case-drop"},
        ],
        "adjudications": [
            {"id": "adjudication-keep", "case_id": "case-keep"},
            {"id": "adjudication-drop", "case_id": "case-drop"},
        ],
        "sanctions": [{"id": "sanction-keep", "case_id": "case-keep"}, {"id": "sanction-drop", "case_id": "case-drop"}],
        "feature_sets": [
            {"id": "feature-keep", "evidence_snapshot_id": "evidence-keep"},
            {"id": "feature-drop", "evidence_snapshot_id": "evidence-drop"},
        ],
        "model_assessments": [
            {"id": "model-keep", "evidence_snapshot_id": "evidence-keep", "feature_set_id": "feature-keep"},
            {"id": "model-drop-evidence", "evidence_snapshot_id": "evidence-drop", "feature_set_id": "feature-keep"},
            {"id": "model-drop-feature", "evidence_snapshot_id": "evidence-keep", "feature_set_id": "feature-drop"},
        ],
    }

    filter_case_dependents(data)

    assert data["case_assignment_history"] == [{"id": "history-keep", "case_id": "case-keep"}]
    assert data["review_leases"] == [{"id": "lease-keep", "case_id": "case-keep"}]
    assert data["driver_submissions"] == [{"id": "submission-keep", "case_id": "case-keep"}]
    assert data["evidence_snapshots"] == [{"id": "evidence-keep", "case_id": "case-keep"}]
    assert data["adjudications"] == [{"id": "adjudication-keep", "case_id": "case-keep"}]
    assert data["sanctions"] == [{"id": "sanction-keep", "case_id": "case-keep"}]
    assert data["feature_sets"] == [{"id": "feature-keep", "evidence_snapshot_id": "evidence-keep"}]
    assert data["model_assessments"] == [
        {"id": "model-keep", "evidence_snapshot_id": "evidence-keep", "feature_set_id": "feature-keep"}
    ]
