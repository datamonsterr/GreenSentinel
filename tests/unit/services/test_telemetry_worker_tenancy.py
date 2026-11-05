"""Trusted tenant processing: persistence, ownership and classifier provenance."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from src.config import Settings
from src.models.classifier import ClassifierResult
from src.services import telemetry_queue_worker as worker
from src.services.case_service import CaseService

ORG = str(uuid4())
OTHER_ORG = str(uuid4())


class FakeClassifier:
    """Decoupled fake fraud classifier for unit tests without external model artifacts."""

    def __init__(self) -> None:
        self.return_value: dict[str, Any] = {
            "category": "ERR-02",
            "priority_tier": 1,
            "priority_score": 80,
            "confidence": 0.9,
            "reason_codes": ["observed_stop"],
            "forensic_brief": "observed evidence",
            "model_version": "r3d-2026.10.18",
            "model_used": "r3d-2026.10.18",
        }
        self.predict = MagicMock(side_effect=self._predict)

    @property
    def model_version(self) -> str:
        return str(self.return_value.get("model_version") or self.return_value.get("model_used") or "r3d-2026.10.18")

    def _predict(self, bundle: dict[str, Any]) -> ClassifierResult:
        cat = self.return_value.get("category", "ERR-02")
        conf = float(self.return_value.get("confidence", 0.9))
        mv = self.model_version
        return ClassifierResult(
            category=cat,
            confidence=conf,
            probabilities={cat: conf},
            guardrail_blocked=False,
            model_version=mv,
            assessment_source="r3d_classifier",
        )

    def assert_not_awaited(self) -> None:
        self.predict.assert_not_called()

    @property
    def await_args(self) -> Any:
        return self.predict.call_args


class Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.row = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.conn.calls.append((sql, params))
        self.row = None
        for table, row in self.conn.rows.items():
            if f"FROM app.{table}" in sql and sql.lstrip().startswith("SELECT"):
                self.row = row
                break
        if "INSERT INTO app.ingest_events" in sql:
            self.row = {"event_id": params[0]}
        if self.conn.fail_write and "INSERT INTO" in sql:
            raise RuntimeError("database unavailable")

    def fetchone(self):
        return self.row


class Connection:
    def __init__(self, event):
        self.calls = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.fail_write = False
        self.rows = {
            "drivers": {"id": event["driver_id"], "organization_id": ORG, "account_status": "active"},
            "passengers": {"id": event["passenger_id"], "organization_id": ORG},
            "vehicles": {"id": event["vehicle_id"], "organization_id": ORG},
            "policy_versions": {"id": event["policy_version_id"], "status": "published"},
        }

    def cursor(self):
        return Cursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


@pytest.fixture
def tenant(monkeypatch):
    event = {
        "organization_id": ORG,
        **{
            key: str(uuid4())
            for key in ("trip_id", "assignment_id", "driver_id", "passenger_id", "vehicle_id", "policy_version_id")
        },
        "pickup": [105.0, 21.0],
        "dropoff": [105.1, 21.1],
        "points": [{"longitude": 105.0, "latitude": 21.0, "occurred_at": "2026-10-14T00:00:00Z"}],
    }
    conn = Connection(event)
    service = CaseService(settings=Settings(app_env="production", database_url="", clerk_secret_key="sk_test_unit"))
    monkeypatch.setattr(service, "_get_db_connection", lambda: conn)
    monkeypatch.setattr(service, "is_driver_suspended", lambda _: False)
    monkeypatch.setattr(worker, "_guardrail_enabled", lambda: False)
    monkeypatch.setattr(worker, "fetch_osrm_route", lambda *a: None)
    fake_classifier = FakeClassifier()
    monkeypatch.setattr("src.api.classifier_routes.get_classifier_service", lambda: fake_classifier)
    assessment = AsyncMock(return_value=fake_classifier.return_value)
    monkeypatch.setattr(worker.JevAssessmentAgent, "assess", assessment)
    monkeypatch.delenv("SIMULATION_TENANT_ALLOW", raising=False)
    return event, conn, service, fake_classifier


@pytest.mark.asyncio
async def test_owned_submission_persists_only_trusted_tenant(tenant):
    event, conn, service, _ = tenant
    result = await worker.process_telemetry_event(event, service, organization_id=ORG)
    assert result["status"] == "processed"
    assert conn.commits == 1
    assert conn.closed
    writes = [(sql, params) for sql, params in conn.calls if "INSERT INTO" in sql]
    assert writes
    for sql, params in writes:
        assert worker.DEFAULT_ORG_ID not in params
        if any(f"INSERT INTO app.{table}" in sql for table in ("trips", "fraud_cases", "ingest_events")):
            assert params[1] == ORG
    assert service._cases[result["case_id"]]["_organization_id"] == ORG
    assert service._cases[result["case_id"]]["assigned_analyst_id"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("table", ["drivers", "passengers", "vehicles", "trips", "trip_assignments"])
async def test_foreign_actor_or_existing_identity_rejected_before_writes(tenant, table):
    event, conn, service, assessment = tenant
    conn.rows[table] = {
        "organization_id": OTHER_ORG,
        "passenger_id": event["passenger_id"],
        "trip_id": event["trip_id"],
        "driver_id": event["driver_id"],
        "vehicle_id": event["vehicle_id"],
    }
    with pytest.raises(HTTPException) as error:
        await worker.process_telemetry_event(event, service, organization_id=ORG)
    assert error.value.status_code == 403
    assert not any("INSERT INTO" in sql for sql, _ in conn.calls)
    assessment.assert_not_awaited()
    assert conn.closed


@pytest.mark.asyncio
async def test_forged_event_org_rejected(tenant):
    event, conn, service, assessment = tenant
    event["organization_id"] = OTHER_ORG
    with pytest.raises(HTTPException) as error:
        await worker.process_telemetry_event(event, service, organization_id=ORG)
    assert error.value.status_code == 403
    assessment.assert_not_awaited()
    assert not conn.calls


@pytest.mark.asyncio
async def test_untrusted_payload_org_cannot_enable_tenant_processing(tenant):
    event, conn, service, _ = tenant
    with pytest.raises(HTTPException) as error:
        await worker.process_telemetry_event(event, service)
    assert error.value.status_code == 403
    assert not any("INSERT INTO" in sql for sql, _ in conn.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["driver_id", "passenger_id", "vehicle_id", "policy_version_id"])
async def test_missing_actor_never_uses_fixture(tenant, key):
    event, conn, service, _ = tenant
    event.pop(key)
    with pytest.raises(HTTPException) as error:
        await worker.process_telemetry_event(event, service, organization_id=ORG)
    assert error.value.status_code == 422
    assert not any("INSERT INTO" in sql for sql, _ in conn.calls)


@pytest.mark.asyncio
async def test_nominal_ignores_forced_case_and_source_label(tenant):
    event, conn, service, assess = tenant
    event.update(force_create_case=True, is_simulation=True, expected_category="ERR-05", scenario="fake_gps")
    assess.return_value["category"] = "no_violation"
    result = await worker.process_telemetry_event(event, service, organization_id=ORG)
    assert result["case_id"] is None
    assert result["category"] == "no_violation"
    assert not service._cases
    assert not any("INSERT INTO app.fraud_cases" in sql for sql, _ in conn.calls)
    projected = assess.await_args.args[0]
    assert "expected_category" not in projected
    assert "scenario" not in projected


@pytest.mark.asyncio
async def test_storage_failure_never_reports_success_or_syncs_case(tenant):
    event, conn, service, _ = tenant
    conn.fail_write = True
    with pytest.raises(RuntimeError, match="database unavailable"):
        await worker.process_telemetry_event(event, service, organization_id=ORG)
    assert conn.rollbacks == 1
    assert conn.commits == 0
    assert conn.closed
    assert not service._cases


@pytest.mark.asyncio
async def test_tenant_processing_requires_durable_storage(tenant, monkeypatch):
    event, _, service, _ = tenant
    monkeypatch.setattr(service, "_get_db_connection", lambda: None)
    with pytest.raises(HTTPException) as error:
        await worker.process_telemetry_event(event, service, organization_id=ORG)
    assert error.value.status_code == 503
    assert not service._cases


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "table,key",
    [
        ("trips", "passenger_id"),
        ("trip_assignments", "trip_id"),
        ("trip_assignments", "driver_id"),
        ("trip_assignments", "vehicle_id"),
    ],
)
async def test_same_org_mismatched_existing_relationship_is_rejected(tenant, table, key):
    event, conn, service, _ = tenant
    conn.rows[table] = {
        "organization_id": ORG,
        **{k: event[k] for k in ("passenger_id", "trip_id", "driver_id", "vehicle_id")},
    }
    conn.rows[table][key] = str(uuid4())
    with pytest.raises(HTTPException) as error:
        await worker.process_telemetry_event(event, service, organization_id=ORG)
    assert error.value.status_code == 403
    assert not any("INSERT INTO" in sql for sql, _ in conn.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["draft", "retired"])
async def test_unpublished_shared_policy_is_rejected(tenant, status):
    event, conn, service, _ = tenant
    conn.rows["policy_versions"]["status"] = status
    with pytest.raises(HTTPException) as error:
        await worker.process_telemetry_event(event, service, organization_id=ORG)
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_suspended_driver_rejected_before_classification(tenant):
    event, conn, service, assess = tenant
    conn.rows["drivers"]["account_status"] = "suspended"
    with pytest.raises(HTTPException) as error:
        await worker.process_telemetry_event(event, service, organization_id=ORG)
    assert error.value.status_code == 403
    assess.assert_not_awaited()


@pytest.mark.asyncio
async def test_actual_classifier_model_is_preserved_in_durable_assessment(tenant):
    event, conn, service, assess = tenant
    assess.return_value["model_used"] = "r3d-2026.10.18"
    assess.return_value["model_version"] = "r3d-2026.10.18"
    await worker.process_telemetry_event(event, service, organization_id=ORG)
    assessment_writes = [params for sql, params in conn.calls if "INSERT INTO app.model_assessments" in sql]
    assert len(assessment_writes) == 1
    assert "r3d-2026.10.18" in assessment_writes[0]


@pytest.mark.asyncio
async def test_nominal_position_coordinates_supported(tenant):
    event, conn, service, assess = tenant
    event["points"] = [{"position": {"type": "Point", "coordinates": [105.0, 21.0]}}]
    assess.return_value["category"] = "no_violation"
    result = await worker.process_telemetry_event(event, service, organization_id=ORG)
    assert result["status"] == "processed"
    assert conn.commits == 1


@pytest.mark.asyncio
async def test_pickup_and_dropoff_address_persisted_to_trips(tenant):
    event, conn, service, assess = tenant
    event["pickup_address"] = "Vincom Center Bà Triệu"
    event["dropoff_address"] = "Hồ Tây"
    result = await worker.process_telemetry_event(event, service, organization_id=ORG)
    assert result["status"] == "processed"
    trip_writes = [(sql, params) for sql, params in conn.calls if "INSERT INTO app.trips" in sql]
    assert len(trip_writes) == 1
    sql, params = trip_writes[0]
    assert "pickup_address" in sql
    assert "dropoff_address" in sql
    assert "Vincom Center Bà Triệu" in params
    assert "Hồ Tây" in params
    # Also verify in-memory service._trips has pickup_address and dropoff_address
    trip_id = event["trip_id"]
    assert service._trips[trip_id].get("pickup_address") == "Vincom Center Bà Triệu"
    assert service._trips[trip_id].get("dropoff_address") == "Hồ Tây"
