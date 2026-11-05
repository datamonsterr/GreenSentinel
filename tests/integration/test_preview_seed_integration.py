"""Integration test to verify deterministic preview seed enrichment for analyst workspace evidence (#366).

Spec: docs/data/PREVIEW_SEED_COVERAGE.md
Ensures all covered fields backed by persisted DB columns are non-null and realistic,
and verifies idempotency across re-runs against the local PostgreSQL test instance.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from dotenv import load_dotenv

try:
    import psycopg
except ImportError:
    psycopg = None

from scripts.seed_preview_enrichment import enrich_preview_cases
from src.services.case_service import get_case_service
from src.services.driver_service import get_driver_scorecard

ORG_ID = "018f2f4e-0000-7000-8000-000000000001"


@pytest.fixture(scope="module")
def db_conn():
    if psycopg is None:
        pytest.skip("psycopg is not installed")
    load_dotenv()
    db_url = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("MIGRATION_DATABASE_URL")
        or "postgresql://postgres:postgrespassword@localhost:5432/postgres"
    )

    conn = None
    for _ in range(3):
        try:
            conn = psycopg.connect(db_url, autocommit=False)
            break
        except Exception:
            import time

            time.sleep(1)

    if conn is None:
        pytest.skip("Local PostgreSQL is unavailable")

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_schema = 'app' AND table_name = 'fraud_cases';"
            )
            if not cur.fetchone():
                conn.close()
                pytest.skip("app.fraud_cases table missing")
        yield conn
        conn.close()
    except Exception as exc:
        pytest.skip(f"Database setup failed: {exc}")


@pytest.mark.asyncio
async def test_preview_seed_enrichment_case_detail(db_conn: Any) -> None:
    """Verify that case detail returns non-null persisted fields for seeded preview cases."""
    # Ensure enrichment is applied
    enrich_preview_cases(conn=db_conn, dry_run=False)

    service = get_case_service()
    case_list = await service.list_cases(organization_id=ORG_ID, limit=10)
    assert case_list.total > 0, "Expected seeded cases in organization"
    assert len(case_list.items) > 0

    valid_models = {
        "VinFast VF e34",
        "VinFast VF 8",
        "VinFast VF 9",
        "VinFast VF 5 Plus",
        "VinFast Evo 200",
        "VinFast Feliz S",
        "VinFast Klara S",
    }
    valid_driver_statuses = {"active", "suspended", "under_review", "offline"}
    valid_match_types = {"auto", "now", "manual_dispatch", "broadcast"}

    # Test across multiple seeded cases
    for case_item in case_list.items[:5]:
        detail = await service.get_case_detail(case_item.id, organization_id=ORG_ID)

        # 1. Trip & Driver Profile fields
        trip = detail.trip
        assert isinstance(trip, dict)

        assert trip.get("vehicle_type") in valid_models, f"Invalid vehicle type: {trip.get('vehicle_type')}"
        assert trip.get("driver_status") in valid_driver_statuses, f"Invalid driver status: {trip.get('driver_status')}"
        assert 4.5 <= float(trip.get("rating", 0.0)) <= 5.0, f"Driver rating out of range: {trip.get('rating')}"
        assert 80.0 <= float(trip.get("acceptance_rate", 0.0)) <= 100.0
        assert 0.0 <= float(trip.get("cancellation_rate", 0.0)) <= 15.0
        assert int(trip.get("total_trips", 0)) >= 100

        # Statements
        driver_stmt = trip.get("driver_statement")
        assert driver_stmt and len(driver_stmt) > 10, "Missing or short driver statement"
        pax_stmt = trip.get("passenger_statement")
        assert pax_stmt and len(pax_stmt) > 10, "Missing or short passenger statement"

        # Trip Fare & Spatial addresses
        fare_vnd = trip.get("fare_amount_vnd")
        assert fare_vnd is not None and int(fare_vnd) >= 30000, f"Invalid trip fare VND: {fare_vnd}"
        assert trip.get("match_type") in valid_match_types
        assert trip.get("pickup_address") and "Hà Nội" in trip.get("pickup_address", "")
        assert trip.get("dropoff_address") and "Hà Nội" in trip.get("dropoff_address", "")
        assert trip.get("district") is not None and len(trip.get("district", "")) > 0

        # 2. Case stall duration (populated for stationary stall categories like ERR-02)
        if detail.case.category == "ERR-02":
            assert detail.case.stall_duration_s is not None
            assert detail.case.stall_duration_s >= 0

        # 3. Telemetry sensor reliability fields (ingest payload extensions)
        assert len(detail.telemetry_samples) > 0, "Expected telemetry samples"
        sample_0 = detail.telemetry_samples[0]
        assert sample_0.get("ping_latency_ms") is not None
        assert 10.0 <= float(sample_0.get("ping_latency_ms", 0)) <= 150.0
        assert sample_0.get("battery_level_pct") is not None
        assert 20.0 <= float(sample_0.get("battery_level_pct", 0)) <= 100.0

        if detail.case.category == "ERR-02":
            assert sample_0.get("gps_accuracy_m") is not None
            assert 0.0 < float(sample_0.get("gps_accuracy_m", 0)) <= 50.0
            assert sample_0.get("drift_distance_m") is not None

        # 4. Preliminary judgment & Motivation assessment
        # Active cases must NOT have fabricated preliminary judgments or adjudications.
        assert detail.preliminary_judgment is None, "Active queue case must have NO preliminary judgment seeded"
        assert detail.adjudication is None, "Active queue case must have NO adjudication seeded"

        assert detail.forensic_brief is not None
        motivation = detail.forensic_brief.motivation_assessment
        assert motivation is not None
        assert motivation.natural_vietnamese_narrative is not None
        assert len(motivation.natural_vietnamese_narrative) > 0
        assert motivation.economic_incentive_reward >= 0.0


@pytest.mark.asyncio
async def test_preview_seed_enrichment_driver_scorecard(db_conn: Any) -> None:
    """Verify that driver 90-day scorecard metrics and past incidents are realistic and populated."""
    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM app.drivers WHERE organization_id = %s LIMIT 3;", (ORG_ID,))
        driver_ids = [row[0] for row in cur.fetchall()]

    assert len(driver_ids) > 0

    for drv_id in driver_ids:
        scorecard = await get_driver_scorecard(str(drv_id), organization_id=ORG_ID)
        assert scorecard.driver_id == str(drv_id)

        # 90d violation ratio grounded to fleet reality (~2.5%–15%)
        assert 0.0 <= scorecard.violation_ratio_90d <= 25.0, (
            f"Violation ratio {scorecard.violation_ratio_90d}% exceeds expected fleet bounds"
        )
        assert scorecard.benchmark_violation_ratio == 5.0
        assert 0.0 <= scorecard.fined_ratio <= 100.0
        assert 10 <= scorecard.repeat_offense_risk_score <= 99
        assert scorecard.tenure_months > 0

        # Past incidents
        assert len(scorecard.past_incidents) == 3, (
            f"Expected 3 past incidents for driver, got {len(scorecard.past_incidents)}"
        )
        for incident in scorecard.past_incidents:
            assert incident.trip_id is not None
            assert incident.occurred_at is not None
            assert incident.violation_type is not None
            assert incident.investigation_finding is not None
            assert incident.action_taken is not None
            assert incident.status in {"exonerated", "penalized", "warned"}


def test_preview_seed_enrichment_idempotency(db_conn: Any) -> None:
    """Verify that re-running enrichment applies 0 duplicate rows and respects immutability."""
    # First re-run: all counts of new rows should be 0
    stats = enrich_preview_cases(conn=db_conn, dry_run=False)

    assert stats["vehicles_enriched"] == 0
    assert stats["telemetry_events_enriched"] == 0
    assert stats["historical_trips_seeded"] == 0
    assert stats["past_adjudications_enriched"] == 0

    # Counts should remain stable
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM app.trips;")
        trips_count_1 = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM app.preliminary_judgments;")
        pj_count_1 = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM app.adjudications;")
        adj_count_1 = cur.fetchone()[0]

    assert pj_count_1 == 0, "Expected 0 preliminary judgments seeded"

    # Second re-run
    stats_2 = enrich_preview_cases(conn=db_conn, dry_run=False)
    assert stats_2["historical_trips_seeded"] == 0
    assert stats_2["past_adjudications_enriched"] == 0

    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM app.trips;")
        trips_count_2 = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM app.preliminary_judgments;")
        pj_count_2 = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM app.adjudications;")
        adj_count_2 = cur.fetchone()[0]

    assert trips_count_1 == trips_count_2
    assert pj_count_1 == pj_count_2
    assert adj_count_1 == adj_count_2


def test_active_cases_remain_unadjudicated_and_unjudged(db_conn: Any) -> None:
    """Integration test asserting that after enrich_preview_cases(apply),
    every case in an active/open/claimable status has zero preliminary_judgments,
    zero adjudications, and unchanged status/version vs before seeding.
    """
    # 1. Snapshot active cases before running enrichment
    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, status, version
            FROM app.fraud_cases
            WHERE status NOT IN ('resolved', 'auto_dismissed', 'dismissed', 'closed')
            ORDER BY id;
            """
        )
        rows_before = cur.fetchall()
        before_active = {r[0]: (r[1], r[2]) for r in rows_before}

    assert len(before_active) > 0, "Expected active cases to exist before seeding"

    # 2. Run enrichment in apply mode
    stats = enrich_preview_cases(conn=db_conn, dry_run=False)
    assert isinstance(stats, dict)

    # 3. Assert active cases invariant holds after enrichment
    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.id, c.status, c.version,
                   (SELECT count(*) FROM app.preliminary_judgments pj WHERE pj.case_id = c.id) as pj_count,
                   (SELECT count(*) FROM app.adjudications a WHERE a.case_id = c.id) as adj_count
            FROM app.fraud_cases c
            WHERE c.status NOT IN ('resolved', 'auto_dismissed', 'dismissed', 'closed')
            ORDER BY c.id;
            """
        )
        rows_after = cur.fetchall()

    assert len(rows_after) == len(before_active), "Active case count changed after enrichment"

    for r in rows_after:
        case_id, current_status, current_version, pj_count, adj_count = r
        assert case_id in before_active, f"Unknown active case {case_id}"
        orig_status, orig_version = before_active[case_id]

        assert pj_count == 0, f"Case {case_id} ({current_status}) has {pj_count} preliminary judgments; expected 0"
        assert adj_count == 0, f"Case {case_id} ({current_status}) has {adj_count} adjudications; expected 0"
        assert current_status == orig_status, f"Case {case_id} status changed from {orig_status} to {current_status}"
        assert current_version == orig_version, (
            f"Case {case_id} version changed from {orig_version} to {current_version}"
        )
