"""Opt-in real PostgreSQL/API queue acceptance on an exclusively owned database."""

import hashlib
import os
from urllib.parse import urlparse
from uuid import uuid4

import psycopg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from psycopg.rows import dict_row

from src.api.auth import Principal, require_principal
from src.api.routes import router
from src.config import Settings
from src.services.case_service import CaseService, get_case_service


@pytest.fixture
def persisted_queue(monkeypatch):
    url = os.getenv("ISSUE143_DATABASE_URL")
    if not url:
        pytest.skip("Set ISSUE143_DATABASE_URL to a migrated isolated issue143_* database")
    target = urlparse(url)
    if target.hostname not in {"localhost", "127.0.0.1"} or not target.path.startswith("/issue143_"):
        pytest.fail("Queue acceptance requires a local isolated issue143_* database")
    service = CaseService(Settings(app_env="development", database_url=url))
    # Only PostgreSQL may satisfy this gate; unavailable storage must fail.
    monkeypatch.setattr(service, "get_redis_client", lambda: None)
    with psycopg.connect(url, row_factory=dict_row) as conn:
        row = conn.execute("""
            SELECT c.id, c.organization_id, p.id AS analyst_id
            FROM app.fraud_cases c
            JOIN app.principals p ON p.organization_id = c.organization_id
            JOIN app.principal_roles pr ON pr.principal_id = p.id
            WHERE pr.role IN ('analyst', 'fraud_analyst', 'senior_analyst', 'admin')
              AND (c.assigned_analyst_id IS NULL OR c.assigned_analyst_id = p.id)
              AND c.status NOT IN ('resolved', 'auto_dismissed')
            ORDER BY c.id, p.id LIMIT 1
        """).fetchone()
        assert row is not None, "Seed an active case and authorized analyst first"
    principal = Principal(
        id=str(row["analyst_id"]), organization_id=str(row["organization_id"]), roles=frozenset({"analyst"})
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_case_service] = lambda: service
    app.dependency_overrides[require_principal] = lambda: principal
    return app, url, row


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["AGREE", "DISAGREE"])
async def test_committed_decision_leaves_active_queues_but_keeps_history(persisted_queue, outcome):
    app, url, row = persisted_queue
    case_id, analyst_id = str(row["id"]), str(row["analyst_id"])
    with psycopg.connect(url) as conn:
        # Seed an explicitly identified historical audit fixture. This gate proves
        # preservation, not production creation of a new decision audit event.
        conn.execute(
            """INSERT INTO app.audit_events
            (organization_id, actor_id, case_id, action, result, request_id, redacted_payload, event_hash)
            VALUES (%s, %s, %s, 'issue143_history_fixture', 'accepted', %s, '{}', %s)""",
            (row["organization_id"], analyst_id, case_id, uuid4(), hashlib.sha256(case_id.encode()).digest()),
        )
        session_id = conn.execute(
            """INSERT INTO app.case_agent_sessions (organization_id, case_id, created_by)
            VALUES (%s, %s, %s) ON CONFLICT (case_id) DO UPDATE SET case_id=EXCLUDED.case_id RETURNING id""",
            (row["organization_id"], case_id, analyst_id),
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO app.case_agent_messages (session_id, turn_id, role, content)
            VALUES (%s, %s, 'user', 'Issue 143 historical conversation fixture')""",
            (session_id, uuid4()),
        )
        conversation_before = conn.execute(
            "SELECT * FROM app.case_agent_messages WHERE session_id=%s ORDER BY sequence", (session_id,)
        ).fetchall()
        audit_before = conn.execute("SELECT * FROM app.audit_events ORDER BY sequence").fetchall()
        evidence_before = conn.execute("SELECT * FROM app.evidence_snapshots WHERE case_id=%s", (case_id,)).fetchall()
        assert evidence_before, "Historical evidence must be present, not an empty preservation assertion"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        claim = await client.post(f"/api/v1/cases/{case_id}/claim", json={"analyst_id": analyst_id})
        assert claim.status_code == 200, claim.text
        detail = await client.get(f"/api/v1/cases/{case_id}")
        assert detail.status_code == 200, detail.text
        version = detail.json()["case"]["version"]
        before = (await client.get("/api/v1/cases", params={"limit": 200})).json()
        assert case_id in [case["id"] for case in before["items"]]
        payload = {
            "analyst_id": analyst_id,
            "outcome": outcome,
            "rationale": "Reviewed the persisted trip evidence and confirmed dismissal.",
            "expected_case_version": version,
        }
        stale = await client.post(
            f"/api/v1/cases/{case_id}/adjudicate", json={**payload, "expected_case_version": version + 99}
        )
        assert stale.status_code == 409, stale.text
        assert (await client.get("/api/v1/cases")).json()["total"] == before["total"]
        decision = await client.post(f"/api/v1/cases/{case_id}/adjudicate", json=payload)
        assert decision.status_code == 200, decision.text
        duplicate = await client.post(f"/api/v1/cases/{case_id}/adjudicate", json=payload)
        assert duplicate.status_code == 409, duplicate.text
        for availability in ("available", "mine"):
            active = (await client.get("/api/v1/cases", params={"availability": availability, "limit": 200})).json()
            assert case_id not in [case["id"] for case in active["items"]]
            if availability == "available":
                assert active["total"] == before["total"] - 1
            page = (
                await client.get("/api/v1/cases", params={"availability": availability, "limit": 2, "offset": 1})
            ).json()
            assert page["total"] == active["total"]
            assert [item["id"] for item in page["items"]] == [item["id"] for item in active["items"][1:3]]
        history = (await client.get("/api/v1/cases", params={"status": "resolved", "limit": 200})).json()
        assert case_id in [case["id"] for case in history["items"]]
        retained = await client.get(f"/api/v1/cases/{case_id}")
        assert retained.status_code == 200
        assert retained.json()["case"]["status"] == "resolved"
    with psycopg.connect(url) as conn:
        decisions = conn.execute(
            "SELECT analyst_id, rationale, outcome FROM app.adjudications WHERE case_id=%s", (case_id,)
        ).fetchall()
        assert decisions == [(row["analyst_id"], payload["rationale"], outcome.lower())]
        assert (
            conn.execute(
                "SELECT * FROM app.case_agent_messages WHERE session_id=%s ORDER BY sequence", (session_id,)
            ).fetchall()
            == conversation_before
        )
        assert conn.execute("SELECT * FROM app.audit_events ORDER BY sequence").fetchall() == audit_before
        assert (
            conn.execute("SELECT * FROM app.evidence_snapshots WHERE case_id=%s", (case_id,)).fetchall()
            == evidence_before
        )


@pytest.mark.asyncio
async def test_transaction_failure_retains_case_and_evidence_request_remains_active(persisted_queue, monkeypatch):
    app, url, row = persisted_queue
    case_id, analyst_id = str(row["id"]), str(row["analyst_id"])

    def publication_failure(*args, **kwargs):
        # Failure occurs after the adjudication INSERT and resolved UPDATE.
        raise RuntimeError("Issue143 controlled publication failure")

    monkeypatch.setattr("src.services.precedent_repository.publish_finalized", publication_failure)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        claim = await client.post(f"/api/v1/cases/{case_id}/claim", json={"analyst_id": analyst_id})
        assert claim.status_code == 200, claim.text
        before = (await client.get(f"/api/v1/cases/{case_id}")).json()["case"]
        response = await client.post(
            f"/api/v1/cases/{case_id}/adjudicate",
            json={
                "analyst_id": analyst_id,
                "outcome": "DISAGREE",
                "rationale": "Rollback acceptance verification",
                "expected_case_version": before["version"],
            },
        )
        assert response.status_code == 503, response.text
        retained = (await client.get(f"/api/v1/cases/{case_id}")).json()["case"]
        assert retained["status"] == before["status"]
        assert retained["version"] == before["version"]
        for availability in ("available", "mine"):
            active = (await client.get("/api/v1/cases", params={"availability": availability, "limit": 200})).json()
            assert case_id in [case["id"] for case in active["items"]]
        with psycopg.connect(url) as conn:
            assert (
                conn.execute("SELECT count(*) FROM app.adjudications WHERE case_id=%s", (case_id,)).fetchone()[0] == 0
            )
        evidence_request = await client.post(
            f"/api/v1/cases/{case_id}/actions",
            json={
                "analyst_id": analyst_id,
                "action_type": "REQUEST_EVIDENCE",
                "notes": "Need pickup evidence",
            },
        )
        assert evidence_request.status_code == 200, evidence_request.text
        for availability in ("available", "mine"):
            active = (await client.get("/api/v1/cases", params={"availability": availability, "limit": 200})).json()
            assert next(case for case in active["items"] if case["id"] == case_id)["status"] == "evidence_requested"
        rejected = await client.post(
            f"/api/v1/cases/{case_id}/actions",
            json={
                "analyst_id": analyst_id,
                "action_type": "ESCALATE",
                "notes": "Unsupported lifecycle remains blocked",
            },
        )
        assert rejected.status_code == 422
