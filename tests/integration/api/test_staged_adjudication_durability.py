"""Opt-in PostgreSQL proof for issue #236's durable storage contract.

Set ``ISSUE236_DATABASE_URL`` to a disposable database with the migrations
applied.  The normal API tests intentionally use memory storage and do not
prove restart durability.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.auth import Principal, require_principal
from src.api.routes import router
from src.config import Settings
from src.services.case_service import CaseService, get_case_service

psycopg = pytest.importorskip("psycopg")


def _url() -> str:
    value = os.getenv("ISSUE236_DATABASE_URL")
    if not value:
        pytest.skip("Set ISSUE236_DATABASE_URL to an isolated migrated PostgreSQL database")
    return value


def _fixture_ids(conn):
    row = conn.execute(
        """
        select c.id, p.id
        from app.fraud_cases c
        join app.principals p on p.organization_id = c.organization_id
        where not exists (
            select 1 from app.preliminary_judgments j where j.case_id = c.id
        )
        limit 1
        """
    ).fetchone()
    if row is None:
        pytest.skip("Disposable database has no uncommitted case/principal pair")
    return row


def test_migration_exposes_append_only_judgment_and_staged_context():
    with psycopg.connect(_url()) as conn:
        columns = set(
            conn.execute(
                """
                select table_name, column_name
                from information_schema.columns
                where table_schema = 'app'
                  and ((table_name = 'preliminary_judgments' and column_name in
                        ('id', 'case_id', 'analyst_id', 'judgment', 'note', 'created_at'))
                    or (table_name = 'adjudications' and column_name = 'staged_context'))
                """
            ).fetchall()
        )
    assert {
        ("preliminary_judgments", name) for name in ("id", "case_id", "analyst_id", "judgment", "note", "created_at")
    } <= columns
    assert ("adjudications", "staged_context") in columns


def test_judgment_survives_connection_restart_and_duplicate_case_is_rejected():
    case_id = analyst_id = judgment_id = None
    url = _url()
    with psycopg.connect(url) as conn:
        case_id, analyst_id = _fixture_ids(conn)
        judgment_id = uuid4()
        conn.execute(
            """
            insert into app.preliminary_judgments (id, case_id, analyst_id, judgment, note)
            values (%s, %s, %s, 'Nghi ngờ vi phạm', 'durability proof')
            """,
            (judgment_id, case_id, analyst_id),
        )
        conn.commit()

    with psycopg.connect(url) as conn:
        row = conn.execute(
            "select id, judgment, note from app.preliminary_judgments where case_id = %s",
            (case_id,),
        ).fetchone()
        assert row == (judgment_id, "Nghi ngờ vi phạm", "durability proof")
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(
                """
                insert into app.preliminary_judgments (case_id, analyst_id, judgment)
                values (%s, %s, 'Chưa đủ cơ sở')
                """,
                (case_id, analyst_id),
            )
        conn.rollback()

        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="append-only"):
            conn.execute(
                "update app.preliminary_judgments set note = 'tampered' where id = %s",
                (judgment_id,),
            )
        conn.rollback()


@pytest_asyncio.fixture
async def durable_case(monkeypatch):
    """Fresh records in an explicitly isolated, fully migrated database."""
    url = _url()
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    ids = {
        name: str(uuid4())
        for name in (
            "org",
            "analyst",
            "driver_principal",
            "passenger",
            "driver",
            "vehicle",
            "trip",
            "assignment",
            "case",
            "policy",
            "snapshot",
            "feature",
            "assessment",
        )
    }
    with psycopg.connect(url) as conn:
        conn.execute("SET search_path = app, extensions, public")
        conn.execute("INSERT INTO app.organizations (id, name) VALUES (%s, '236 disposable')", (ids["org"],))
        for name in ("analyst", "driver_principal"):
            conn.execute(
                "INSERT INTO app.principals (id, organization_id, external_subject, display_name) VALUES (%s,%s,%s,%s)",
                (ids[name], ids["org"], ids[name], name),
            )
        conn.execute("INSERT INTO app.principal_roles (principal_id, role) VALUES (%s,'analyst')", (ids["analyst"],))
        conn.execute("INSERT INTO app.passengers (id, organization_id) VALUES (%s,%s)", (ids["passenger"], ids["org"]))
        conn.execute(
            "INSERT INTO app.drivers (id, organization_id, principal_id, partner_type) VALUES (%s,%s,%s,'fleet')",
            (ids["driver"], ids["org"], ids["driver_principal"]),
        )
        conn.execute(
            """INSERT INTO app.vehicles (id, organization_id, registration_ref, vehicle_type, service_class, telemetry_source)
               VALUES (%s,%s,%s,'car','standard','simulator')""",
            (ids["vehicle"], ids["org"], ids["vehicle"]),
        )
        conn.execute(
            """INSERT INTO app.trips (id, organization_id, passenger_id, requested_at, pickup, dropoff,
                                      requested_service_class, status)
               VALUES (%s,%s,%s,now(),'SRID=4326;POINT(105.8 21.0)'::geography,
                       'SRID=4326;POINT(105.81 21.01)'::geography,'standard','cancelled')""",
            (ids["trip"], ids["org"], ids["passenger"]),
        )
        conn.execute(
            """INSERT INTO app.trip_assignments (id, trip_id, driver_id, vehicle_id, state, offered_at)
               VALUES (%s,%s,%s,%s,'cancelled',now())""",
            (ids["assignment"], ids["trip"], ids["driver"], ids["vehicle"]),
        )
        conn.execute(
            """INSERT INTO app.fraud_cases (id, organization_id, assignment_id, status, suspected_category,
                                           priority_tier, priority_score, priority_rule_version, assigned_analyst_id)
               VALUES (%s,%s,%s,'in_review','ERR-02',1,80,'236-test',%s)""",
            (ids["case"], ids["org"], ids["assignment"], ids["analyst"]),
        )
        conn.execute(
            """INSERT INTO app.policy_versions (id, version, status, source_hash, action_matrix)
               VALUES (%s,%s,'published',%s,'{}')""",
            (ids["policy"], ids["policy"], b"236-test"),
        )
        conn.execute(
            """INSERT INTO app.evidence_snapshots (id, case_id, version, policy_version_id, event_cutoff_at,
                                                  stage, dossier, dossier_hash)
               VALUES (%s,%s,1,%s,now(),'post_cancellation','{}',%s)""",
            (ids["snapshot"], ids["case"], ids["policy"], b"236-test"),
        )
        conn.execute(
            """INSERT INTO app.feature_sets (id, evidence_snapshot_id, preprocessing_version, window_start,
                                            window_end, telemetry_coverage, max_gap_s, stationary_duration_s, features)
               VALUES (%s,%s,'236-test',now(),now(),1,0,240,'{}')""",
            (ids["feature"], ids["snapshot"]),
        )
        conn.execute(
            """INSERT INTO app.model_assessments (id, evidence_snapshot_id, feature_set_id, provider, model_id,
                  prompt_version, output_schema_version, status, category, confidence, score_semantics, raw_response)
               VALUES (%s,%s,%s,'fixture','fixture','236-test',1,'completed','ERR-02',0.92,
                       'uncalibrated','{"recommended_action":"Agree"}')""",
            (ids["assessment"], ids["snapshot"], ids["feature"]),
        )
        conn.execute(
            """INSERT INTO app.review_leases (case_id, analyst_id, token_hash, case_version, evidence_snapshot_id, expires_at)
               VALUES (%s,%s,%s,1,%s,now()+interval '1 hour')""",
            (ids["case"], ids["analyst"], uuid4().bytes, ids["snapshot"]),
        )

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    settings = Settings(app_env="test", test_auth_enabled=True, database_url=url, redis_url="")

    def restart_service():
        service = CaseService(settings)
        app.dependency_overrides[get_case_service] = lambda: service

    restart_service()
    app.dependency_overrides[require_principal] = lambda: Principal(
        id=ids["analyst"], organization_id=ids["org"], roles=frozenset({"analyst"})
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, ids, restart_service


async def test_http_commit_survives_service_restart_and_rejects_replacement(durable_case):
    client, ids, restart = durable_case
    base = f"/api/v1/cases/{ids['case']}"
    payload = {"analyst_id": ids["analyst"], "judgment": "Nghi oan/bất khả kháng", "note": "Độc lập"}
    saved = await client.post(f"{base}/preliminary-assessment", json=payload)
    assert saved.status_code == 200, saved.text
    restart()
    restored = (await client.get(base)).json()
    assert restored["preliminary_judgment"] == saved.json()
    retry = await client.post(f"{base}/preliminary-assessment", json=payload)
    assert retry.status_code == 200, retry.text
    assert retry.json()["id"] == saved.json()["id"]
    replacement = await client.post(f"{base}/preliminary-assessment", json={**payload, "judgment": "Nghi ngờ vi phạm"})
    assert replacement.status_code == 409


async def test_http_final_context_survives_restart_in_detail_history_and_audit(durable_case):
    client, ids, restart = durable_case
    base = f"/api/v1/cases/{ids['case']}"
    saved = await client.post(
        f"{base}/preliminary-assessment", json={"analyst_id": ids["analyst"], "judgment": "Nghi oan-bất khả kháng"}
    )
    assert saved.status_code == 200, saved.text
    result = await client.post(
        f"{base}/adjudicate",
        json={
            "analyst_id": ids["analyst"],
            "outcome": "DISAGREE",
            "rationale": "1234567890",
            "expected_case_version": 1,
            "preliminary_judgment_id": saved.json()["id"],
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["delta"] == "mismatch"
    restart()
    decision = (await client.get(base)).json()["adjudication"]
    assert decision["preliminary_judgment_id"] == saved.json()["id"]
    assert decision["ai_suggestion"] == {"category": "ERR-02", "confidence": 0.92, "recommended_action": "Agree"}
    history = (await client.get("/api/v1/cases/history")).json()["items"]
    item = next(row for row in history if row["id"] == ids["case"])
    audit = (await client.get("/api/v1/analyst/audit")).json()["ledger"]
    ledger = next(row for row in audit if row["case_id"] == ids["case"])
    for row in (decision, item, ledger):
        assert row["preliminary_judgment"]["judgment"] == "Nghi oan-bất khả kháng"
        assert row["delta"] == "mismatch"


async def test_http_unknown_judgment_cannot_change_persisted_version(durable_case):
    client, ids, _ = durable_case
    base = f"/api/v1/cases/{ids['case']}"
    result = await client.post(
        f"{base}/adjudicate",
        json={
            "analyst_id": ids["analyst"],
            "outcome": "DISAGREE",
            "rationale": "1234567890",
            "expected_case_version": 1,
            "preliminary_judgment_id": str(uuid4()),
        },
    )
    assert result.status_code == 409, result.text
    assert (await client.get(base)).json()["case"]["version"] == 1
