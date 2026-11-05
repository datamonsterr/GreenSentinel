"""Unit tests for analyst workload assignment and principal mapping (#573)."""

from typing import Any
from uuid import uuid4

import pytest

from src.config import Settings
from src.models.classifier import ClassifierResult
from src.services import telemetry_queue_worker as worker
from src.services.case_service import CaseService

ORG_ID = str(uuid4())
FRAUD_ANALYST_ID = str(uuid4())


class FakeClassifier:
    def __init__(self) -> None:
        self.return_value = {
            "category": "ERR-02",
            "priority_tier": 1,
            "priority_score": 85,
            "confidence": 0.85,
            "reason_codes": ["stationary_duration_over_180s"],
            "forensic_brief": "Observed stopping",
            "model_version": "r3d",
        }

    @property
    def model_version(self) -> str:
        return "r3d"

    def predict(self, bundle: dict[str, Any]) -> ClassifierResult:
        return ClassifierResult(
            category="ERR-02",
            confidence=0.85,
            probabilities={"ERR-02": 0.85},
            guardrail_blocked=False,
            model_version="r3d",
            assessment_source="r3d_classifier",
            artifact_sha="sha256:test",
            feature_ms=1.0,
            inference_ms=1.0,
        )


class MockCursor:
    def __init__(self, conn: "MockConnection"):
        self.conn = conn
        self.row: Any = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql: str, params: Any = None):
        self.conn.executed_statements.append((sql, params))
        self.row = None

        if "FROM app.drivers" in sql:
            self.row = {
                "id": params[0] if params else str(uuid4()),
                "organization_id": ORG_ID,
                "account_status": "active",
            }
        elif "FROM app.passengers" in sql:
            self.row = {"id": params[0] if params else str(uuid4()), "organization_id": ORG_ID}
        elif "FROM app.vehicles" in sql:
            self.row = {"id": params[0] if params else str(uuid4()), "organization_id": ORG_ID}
        elif "FROM app.policy_versions" in sql:
            self.row = {"id": params[0] if params else str(uuid4()), "status": "published"}
        elif "FROM app.principals p" in sql and "candidate" in sql:
            # Check if query allows fraud_analyst
            assert "fraud_analyst" in sql, "Auto-assignment query must include 'fraud_analyst' role"
            self.row = {"id": FRAUD_ANALYST_ID}
        elif "INSERT INTO app.fraud_cases" in sql:
            self.row = {"id": str(uuid4())}
        elif "SELECT id FROM app.evidence_snapshots" in sql:
            self.row = None
        elif "SELECT id FROM app.feature_sets" in sql:
            self.row = None
        elif "SELECT id FROM app.model_assessments" in sql:
            self.row = None
        elif "INSERT INTO app.ingest_events" in sql:
            self.row = {"event_id": str(uuid4())}

    def fetchone(self):
        return self.row


class MockConnection:
    def __init__(self):
        self.executed_statements: list[tuple[str, Any]] = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return MockCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_telemetry_worker_auto_assigns_fraud_analyst_role(monkeypatch):
    """Clerk provisioned analysts have role 'fraud_analyst'. Auto-assignment must include them."""
    event = {
        "organization_id": ORG_ID,
        "trip_id": str(uuid4()),
        "assignment_id": str(uuid4()),
        "driver_id": str(uuid4()),
        "passenger_id": str(uuid4()),
        "vehicle_id": str(uuid4()),
        "policy_version_id": str(uuid4()),
        "pickup": [105.8542, 21.0285],
        "dropoff": [105.8600, 21.0350],
        "points": [{"longitude": 105.8542, "latitude": 21.0285, "occurred_at": "2026-10-19T12:00:00Z"}],
    }

    conn = MockConnection()
    service = CaseService(settings=Settings(app_env="production", database_url="", clerk_secret_key=""))
    monkeypatch.setattr(service, "_get_db_connection", lambda: conn)
    monkeypatch.setattr(service, "is_driver_suspended", lambda _: False)
    monkeypatch.setattr(worker, "_guardrail_enabled", lambda: False)
    monkeypatch.setattr(worker, "fetch_osrm_route", lambda *a: None)

    classifier = FakeClassifier()
    monkeypatch.setattr("src.api.classifier_routes.get_classifier_service", lambda: classifier)

    await worker.process_telemetry_event(event, service, organization_id=ORG_ID)

    # Verify that the candidate analyst query was executed and included fraud_analyst
    candidate_queries = [
        (sql, params)
        for sql, params in conn.executed_statements
        if "FROM app.principals p" in sql and "candidate" in sql
    ]
    assert len(candidate_queries) == 1
    sql, params = candidate_queries[0]
    assert "fraud_analyst" in sql

    # Verify fraud_cases was inserted with the fraud_analyst's ID
    case_inserts = [(sql, params) for sql, params in conn.executed_statements if "INSERT INTO app.fraud_cases" in sql]
    assert len(case_inserts) == 1
    _, case_params = case_inserts[0]
    assert FRAUD_ANALYST_ID in case_params


def test_find_least_loaded_analyst_query_includes_fraud_analyst():
    """CaseService.select_least_loaded_analyst must query for 'fraud_analyst' role."""
    service = CaseService(settings=Settings(app_env="production", database_url="", clerk_secret_key=""))
    conn = MockConnection()
    with conn.cursor() as cur:
        service.select_least_loaded_analyst(cur, ORG_ID)

    candidate_queries = [
        (sql, params)
        for sql, params in conn.executed_statements
        if "FROM app.principals p" in sql and "candidate" in sql
    ]
    assert len(candidate_queries) == 1
    sql, _ = candidate_queries[0]
    assert "fraud_analyst" in sql
