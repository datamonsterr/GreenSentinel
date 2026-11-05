"""Migrated-Postgres proof for S2-F09 durable precedent history."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover
    psycopg = None
    dict_row = None

from src.services.precedent_repository import (
    PrecedentPersistenceError,
    get_finalized,
    get_finalized_by_case,
    get_legacy_read_only,
    list_finalized,
    publish_finalized,
    record_application_from_latest_view,
    record_reuse,
)

pytestmark = pytest.mark.docker

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "db" / "migrations" / "20261003090000_durable_solved_case_precedents.sql"
ROLLBACK = ROOT / "db" / "rollbacks" / "20261003090000_durable_solved_case_precedents.down.sql"


@pytest.fixture(scope="module")
def db_conn():
    if psycopg is None:
        pytest.skip("psycopg is not installed")
    url = os.getenv("ISSUE66_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("Set ISSUE66_DATABASE_URL or DATABASE_URL to a migrated isolated database")
    conn = None
    try:
        try:
            conn = psycopg.connect(url, row_factory=dict_row, connect_timeout=2)
        except psycopg.OperationalError:
            pytest.skip("Configured PostgreSQL database is unavailable")
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('app.solved_case_contexts') AS table_name")
            if not cur.fetchone()["table_name"]:
                pytest.skip("S2-F09 migration is not applied")
        yield conn
    finally:
        if conn is not None:
            conn.close()


@pytest.fixture(scope="module")
def contexts(db_conn):
    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (fc.id)
                   fc.id AS case_id, fc.organization_id, fc.assignment_id,
                   es.id AS evidence_snapshot_id, es.policy_version_id,
                   p.id AS analyst_id, d.principal_id AS driver_principal_id
            FROM app.fraud_cases fc
            JOIN app.evidence_snapshots es ON es.case_id = fc.id
            JOIN app.trip_assignments ta ON ta.id = fc.assignment_id
            JOIN app.drivers d ON d.id = ta.driver_id
            JOIN app.principals p ON p.organization_id = fc.organization_id
            JOIN app.principal_roles pr ON pr.principal_id = p.id AND pr.role = 'analyst'
            WHERE NOT EXISTS (SELECT 1 FROM app.adjudications a WHERE a.case_id = fc.id)
            ORDER BY fc.id, es.version DESC
            LIMIT 3
            """
        )
        rows = [dict(row) for row in cur.fetchall()]
    if len(rows) < 3:
        pytest.skip("Need three unadjudicated seeded cases")

    outcomes = ("dismiss", "approve")
    items = []
    for index, (row, outcome) in enumerate(zip(rows[:2], outcomes, strict=True)):
        adjudication_id = uuid4()
        approved_at = f"2026-10-03T0{index + 1}:00:00+00:00"
        with db_conn.cursor() as cur:
            cur.execute(
                "UPDATE app.fraud_cases SET status = 'resolved', resolved_at = %s WHERE id = %s",
                (approved_at, row["case_id"]),
            )
            cur.execute(
                """
                INSERT INTO app.adjudications (
                    id, case_id, evidence_snapshot_id, policy_version_id, analyst_id,
                    outcome, rationale, explicit_human_approval,
                    idempotency_key, request_hash, approved_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, true, %s, %s, %s)
                """,
                (
                    adjudication_id,
                    row["case_id"],
                    row["evidence_snapshot_id"],
                    row["policy_version_id"],
                    row["analyst_id"],
                    outcome,
                    f"Human rationale for {outcome} case",
                    uuid4(),
                    bytes.fromhex("ab" * 32),
                    approved_at,
                ),
            )
        item = publish_finalized(
            db_conn,
            case_id=str(row["case_id"]),
            organization_id=str(row["organization_id"]),
            published_by=str(row["analyst_id"]),
        )
        items.append(item)
    db_conn.commit()
    return {"dismissed": items[0], "approved": items[1], "incomplete": rows[2], "rows": rows}


def test_round_trip_reload_covers_dismissed_approved_and_incomplete(db_conn, contexts):
    dismissed = contexts["dismissed"]
    approved = contexts["approved"]
    assert dismissed.verdict == "dismiss"
    assert approved.verdict == "approve"
    assert dismissed.workflow_trace.final_decision.explicit_human_approval is True
    assert dismissed.workflow_trace.driver_response_summary
    assert dismissed.provenance.driver_submission_id
    assert any(ref.startswith("driver_submission:") for ref in dismissed.workflow_trace.source_refs)
    assert dismissed.workflow_trace.related_policies == []
    assert approved.provenance.conversation_state == "linked"
    assert approved.provenance.driver_submission_id

    reloaded = get_finalized(
        db_conn,
        precedent_id=dismissed.id,
        organization_id=dismissed.provenance.organization_id,
    )
    assert reloaded == dismissed
    assert (
        get_finalized(db_conn, precedent_id="not-a-uuid", organization_id=dismissed.provenance.organization_id) is None
    )
    assert (
        get_finalized_by_case(
            db_conn,
            case_id="not-a-uuid",
            organization_id=dismissed.provenance.organization_id,
        )
        is None
    )

    incomplete = contexts["incomplete"]
    with pytest.raises(PrecedentPersistenceError, match="signed adjudication"):
        publish_finalized(
            db_conn,
            case_id=str(incomplete["case_id"]),
            organization_id=str(incomplete["organization_id"]),
            published_by=str(incomplete["analyst_id"]),
        )
    db_conn.rollback()


def test_tenant_scope_and_reuse_history_do_not_change_decisions(db_conn, contexts):
    precedent = contexts["dismissed"]
    target = contexts["incomplete"]
    org_id = precedent.provenance.organization_id
    actor_id = precedent.provenance.published_by
    assert list_finalized(db_conn, organization_id=str(uuid4())) == []

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT outcome, rationale FROM app.adjudications WHERE id = %s", (precedent.provenance.adjudication_id,)
        )
        before = dict(cur.fetchone())

    record_reuse(
        db_conn,
        organization_id=org_id,
        current_case_id=str(target["case_id"]),
        precedent=precedent,
        actor_id=actor_id,
        action="viewed",
        similarity_score=0.81,
        retrieval_model="deterministic_test",
        matching_factors=["same violation code"],
    )
    application_id = record_application_from_latest_view(
        db_conn,
        organization_id=org_id,
        current_case_id=str(target["case_id"]),
        precedent_id=precedent.id,
        actor_id=actor_id,
    )
    db_conn.commit()
    assert application_id

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT outcome, rationale FROM app.adjudications WHERE id = %s", (precedent.provenance.adjudication_id,)
        )
        assert dict(cur.fetchone()) == before
        cur.execute("SELECT action, score_semantics FROM app.precedent_reuse_history ORDER BY created_at")
        history = [dict(row) for row in cur.fetchall()]
    assert [row["action"] for row in history[-2:]] == ["viewed", "applied"]
    assert all("not_adjudication" in row["score_semantics"] for row in history[-2:])

    other_org = uuid4()
    other_actor = uuid4()
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO app.organizations (id, name) VALUES (%s, 'Other tenant')", (other_org,))
        cur.execute(
            """
            INSERT INTO app.principals (id, organization_id, external_subject, display_name)
            VALUES (%s, %s, %s, 'Other analyst')
            """,
            (other_actor, other_org, f"other-{other_actor}"),
        )
    db_conn.commit()
    with pytest.raises(Exception, match="tenant/provenance"):
        record_reuse(
            db_conn,
            organization_id=org_id,
            current_case_id=str(target["case_id"]),
            precedent=precedent,
            actor_id=str(other_actor),
            action="viewed",
            similarity_score=0.81,
            retrieval_model="deterministic_test",
            matching_factors=[],
        )
    db_conn.rollback()


def test_finalized_and_legacy_records_are_read_only(db_conn, contexts):
    precedent = contexts["dismissed"]
    with pytest.raises(Exception, match="append-only"):
        with db_conn.cursor() as cur:
            cur.execute("UPDATE app.solved_case_contexts SET title = 'mutated' WHERE id = %s", (precedent.id,))
    db_conn.rollback()

    legacy_id = uuid4()
    legacy_case_id = precedent.case_id
    org_id = precedent.provenance.organization_id
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO app.precedent_workflows (
                id, case_id, violation_code, claim_type, title, driver_statement_summary,
                workflow_trace, verdict, confidence_score
            ) VALUES (%s, %s, 'ERR-02', 'legacy', 'Legacy appealed record', '', '{}'::jsonb, 'appealed', 0)
            """,
            (legacy_id, legacy_case_id),
        )
    db_conn.commit()
    legacy = get_legacy_read_only(
        db_conn,
        precedent_id=str(legacy_id),
        organization_id=org_id,
    )
    assert legacy.provenance.source_kind == "legacy_appeal"
    assert legacy.provenance.eligible_for_reuse is False
    assert (
        get_legacy_read_only(
            db_conn,
            precedent_id=str(legacy_id),
            organization_id=str(uuid4()),
        )
        is None
    )
    with pytest.raises(Exception, match="append-only"):
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM app.precedent_workflows WHERE id = %s", (legacy_id,))
    db_conn.rollback()


def test_z_rollback_and_forward_migration_are_executable(db_conn):
    rollback_sql = ROLLBACK.read_text(encoding="utf-8")
    migration_sql = MIGRATION.read_text(encoding="utf-8")
    with db_conn.cursor() as cur:
        cur.execute(rollback_sql)
        cur.execute("SELECT to_regclass('app.precedent_workflows') AS legacy_table")
        assert cur.fetchone()["legacy_table"] == "precedent_workflows"
        cur.execute(migration_sql)
        cur.execute("SELECT to_regclass('app.solved_case_contexts') AS durable_table")
        assert cur.fetchone()["durable_table"] == "solved_case_contexts"
    db_conn.commit()
