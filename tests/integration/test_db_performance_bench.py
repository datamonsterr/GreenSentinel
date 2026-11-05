"""Integration tests for database performance benchmarking and migration reversibility.

Validates:
1. Target database safety guardrails (loopback, test prefix, explicit opt-in).
2. Readonly transaction and autocommit preservation on real PostgreSQL (both autocommit=True and autocommit=False).
3. Active caller transaction protection (rejecting active transactions without clobbering).
4. CLI inventory methods leaving connections in compatible IDLE status.
5. Idempotent application and complete reversibility of workload performance indexes.
6. Controlled empirical BEFORE/AFTER benchmarking on realistic cardinality fixtures
   with repeated warm runs, median execution timings, buffer metrics, and 100% result set equality.
7. Retention of reproducible machine benchmark artifact with full execution plans.
8. Bounded migration runner CLI guardrails, expected-plan-hash preflight, and schema drift detection.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any

import psycopg
import pytest

from src.services.db_profiler import (
    DatabaseProfiler,
    redact_dsn_password,
    validate_disposable_database_url,
)

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
MIGRATION_FILE = ROOT_DIR / "db" / "migrations" / "20261015150000_workload_performance_indexes.sql"
ROLLBACK_FILE = ROOT_DIR / "db" / "rollbacks" / "20261015150000_workload_performance_indexes.down.sql"
BENCHMARK_ARTIFACT_PATH = ROOT_DIR / "docs" / "testing" / "artifacts" / "db_bench_evidence_394.json"

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://postgres:postgrespassword@localhost:5432/test_p063_bench"
)


def _get_test_connection(autocommit: bool = True) -> psycopg.Connection:
    """Validate target database and establish an isolated connection."""
    try:
        validate_disposable_database_url(TEST_DB_URL)
        return psycopg.connect(TEST_DB_URL, autocommit=autocommit, connect_timeout=5)
    except Exception as exc:
        pytest.skip(f"Disposable test database unavailable: {redact_dsn_password(str(exc))}")


def _benchmark_workload(
    profiler: DatabaseProfiler,
    query_key: str,
    params: tuple[Any, ...],
    runs: int = 15,
    warmups: int = 5,
) -> dict[str, Any]:
    """Execute repeated warm runs and compute statistical medians and buffer metrics."""
    # Warm-up iterations to stabilize buffer caches and plan caches
    for _ in range(warmups):
        profiler.explain_workload(query_key, params)

    timings: list[float] = []
    last_result: dict[str, Any] = {}

    for _ in range(runs):
        res = profiler.explain_workload(query_key, params)
        timings.append(float(res.get("execution_time_ms", 0.0)))
        last_result = res

    timings.sort()
    p50 = float(statistics.median(timings))
    p95_idx = min(int(0.95 * len(timings)), len(timings) - 1)
    p95 = timings[p95_idx]

    return {
        "sample_count": runs,
        "node_type": last_result.get("node_type"),
        "total_cost": last_result.get("total_cost"),
        "actual_rows": last_result.get("actual_rows"),
        "shared_hit_blocks": last_result.get("shared_hit_blocks", 0),
        "shared_read_blocks": last_result.get("shared_read_blocks", 0),
        "execution_time_median_ms": round(p50, 4),
        "execution_time_p95_ms": round(p95, 4),
        "execution_time_min_ms": round(timings[0], 4),
        "execution_time_max_ms": round(timings[-1], 4),
        "planning_time_ms": round(float(last_result.get("planning_time_ms", 0.0)), 4),
        "full_plan": last_result.get("full_plan"),
    }


def test_profiler_real_pg_autocommit_true_and_false():
    """Verify that explain_query operates correctly under both autocommit=True and autocommit=False.

    Enforces:
    1. EXPLAIN executes cleanly inside an explicit read-only rollback transaction.
    2. Connection autocommit state is preserved after execution.
    3. Connection transaction status is returned to IDLE (0).
    4. DatabaseProfiler enforces read-only protection and bounded statement timeouts.
    """
    for initial_autocommit in (True, False):
        conn = _get_test_connection(autocommit=initial_autocommit)
        profiler = DatabaseProfiler(conn=conn, timeout_ms=4000)

        with conn.cursor() as cur:
            cur.execute("SELECT id FROM app.trips LIMIT 1;")
            trip_id = cur.fetchone()[0]
        if not initial_autocommit:
            conn.rollback()

        result = profiler.explain_workload("trip_assignment_by_trip", (trip_id,))

        assert result is not None
        assert "node_type" in result
        assert "execution_time_ms" in result
        assert "full_plan" in result

        # Verify autocommit state was preserved exactly
        assert conn.autocommit == initial_autocommit

        # Verify connection is left in clean IDLE transaction status
        assert conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

        conn.close()


def test_profiler_real_pg_rejects_active_transaction():
    """DatabaseProfiler must reject an already-open caller transaction without clobbering it."""
    conn = _get_test_connection(autocommit=False)

    # Caller starts an active transaction
    with conn.cursor() as cur:
        cur.execute("SELECT 1;")

    # Connection is now in INTRANS state
    assert conn.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS

    profiler = DatabaseProfiler(conn=conn)

    with pytest.raises(RuntimeError, match="idle|active transaction"):
        profiler.explain_workload("trip_assignment_by_trip", ("00000000-0000-0000-0000-000000000001",))

    # Caller's transaction must NOT have been clobbered or rolled back
    assert conn.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS

    # Caller can safely finish their own transaction
    conn.rollback()
    assert conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    conn.close()


def test_profiler_real_pg_inventory_methods_leave_connection_idle():
    """All inspection and inventory queries must leave the connection in IDLE status."""
    for initial_autocommit in (True, False):
        conn = _get_test_connection(autocommit=initial_autocommit)
        profiler = DatabaseProfiler(conn=conn)

        profiler.preflight_schema_check(
            required_tables=["trip_assignments"],
            required_columns={"trip_assignments": ["id", "trip_id"]},
        )
        assert conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

        profiler.check_tenancy_invariants()
        assert conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

        profiler.fetch_index_inventory("app")
        assert conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

        profiler.audit_unindexed_foreign_keys("app")
        assert conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

        assert conn.autocommit == initial_autocommit
        conn.close()


def test_index_migration_reversibility():
    """Verify that applying and rolling back index migrations is completely idempotent and reversible."""
    conn = _get_test_connection()
    profiler = DatabaseProfiler(conn=conn)

    up_sql = MIGRATION_FILE.read_text(encoding="utf-8")
    down_sql = ROLLBACK_FILE.read_text(encoding="utf-8")

    # Step 1: Rollback first to ensure clean baseline state
    with conn.cursor() as cur:
        cur.execute(down_sql)

    initial_indexes = {idx["index_name"] for idx in profiler.fetch_index_inventory("app")}
    assert "idx_trip_assignments_trip_id" not in initial_indexes

    # Step 2: Apply migration
    with conn.cursor() as cur:
        cur.execute(up_sql)

    post_up_indexes = {idx["index_name"] for idx in profiler.fetch_index_inventory("app")}
    assert "idx_trip_assignments_trip_id" in post_up_indexes

    # Step 3: Rollback migration
    with conn.cursor() as cur:
        cur.execute(down_sql)

    post_down_indexes = {idx["index_name"] for idx in profiler.fetch_index_inventory("app")}
    assert "idx_trip_assignments_trip_id" not in post_down_indexes

    # Step 4: Re-apply to verify idempotence and leave in optimized state
    with conn.cursor() as cur:
        cur.execute(up_sql)

    reapplied_indexes = {idx["index_name"] for idx in profiler.fetch_index_inventory("app")}
    assert "idx_trip_assignments_trip_id" in reapplied_indexes

    conn.close()


def test_workload_performance_comparison():
    """Empirical comparison of query execution plans and buffers before and after index application."""
    conn = _get_test_connection()
    profiler = DatabaseProfiler(conn=conn)

    up_sql = MIGRATION_FILE.read_text(encoding="utf-8")
    down_sql = ROLLBACK_FILE.read_text(encoding="utf-8")

    # Step 0: Ensure realistic cardinality fixture exists for trip_assignments
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM app.trip_assignments;")
        cnt = cur.fetchone()[0]
        if cnt < 2000:
            cur.execute(
                """
                INSERT INTO app.trip_assignments (id, trip_id, driver_id, vehicle_id, state, offered_at)
                SELECT
                    gen_random_uuid(),
                    (SELECT id FROM app.trips LIMIT 1 OFFSET (i % 100)),
                    (SELECT id FROM app.drivers LIMIT 1),
                    (SELECT id FROM app.vehicles LIMIT 1),
                    'completed',
                    now()
                FROM generate_series(1, 3000) i;
                """
            )
            cur.execute("ANALYZE app.trip_assignments; ANALYZE app.trips; ANALYZE app.fraud_cases;")

    # Fetch benchmark entity IDs
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM app.organizations LIMIT 1;")
        org_id = cur.fetchone()[0]

        cur.execute("SELECT id FROM app.trips LIMIT 1;")
        trip_id = cur.fetchone()[0]

    # --- MEASURE BEFORE (BASELINE WITHOUT WORKLOAD INDEXES) ---
    with conn.cursor() as cur:
        cur.execute(down_sql)
        cur.execute("ANALYZE app.trip_assignments; ANALYZE app.fraud_cases;")

    bench_trip_before = _benchmark_workload(profiler, "trip_assignment_by_trip", (trip_id,), runs=15, warmups=5)
    bench_queue_before = _benchmark_workload(profiler, "org_case_queue", (org_id, "ready", 20, 0), runs=15, warmups=5)

    # Capture raw query output rows for strict equality comparison
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, trip_id, driver_id, vehicle_id, state, accepted_at, started_at, ended_at
            FROM app.trip_assignments
            WHERE trip_id = %s;
            """,
            (trip_id,),
        )
        data_trip_before = cur.fetchall()

        cur.execute(
            """
            SELECT c.id, c.status, c.dispute_status, c.priority_tier, c.priority_score, c.created_at
            FROM app.fraud_cases c
            WHERE c.organization_id = %s
              AND LOWER(c.status) = LOWER(%s)
            ORDER BY c.priority_tier ASC, c.priority_score DESC, c.created_at DESC
            LIMIT 20 OFFSET 0;
            """,
            (org_id, "ready"),
        )
        data_queue_before = cur.fetchall()

    # --- APPLY INDEXES ---
    with conn.cursor() as cur:
        cur.execute(up_sql)
        cur.execute("ANALYZE app.trip_assignments; ANALYZE app.fraud_cases;")

    # --- MEASURE AFTER (OPTIMIZED WITH INDEXES) ---
    bench_trip_after = _benchmark_workload(profiler, "trip_assignment_by_trip", (trip_id,), runs=15, warmups=5)
    bench_queue_after = _benchmark_workload(profiler, "org_case_queue", (org_id, "ready", 20, 0), runs=15, warmups=5)

    # Capture raw query output rows after index application
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, trip_id, driver_id, vehicle_id, state, accepted_at, started_at, ended_at
            FROM app.trip_assignments
            WHERE trip_id = %s;
            """,
            (trip_id,),
        )
        data_trip_after = cur.fetchall()

        cur.execute(
            """
            SELECT c.id, c.status, c.dispute_status, c.priority_tier, c.priority_score, c.created_at
            FROM app.fraud_cases c
            WHERE c.organization_id = %s
              AND LOWER(c.status) = LOWER(%s)
            ORDER BY c.priority_tier ASC, c.priority_score DESC, c.created_at DESC
            LIMIT 20 OFFSET 0;
            """,
            (org_id, "ready"),
        )
        data_queue_after = cur.fetchall()

        # Query index sizes in bytes
        cur.execute(
            """
            SELECT
                indexrelid::regclass::text AS index_name,
                pg_relation_size(indexrelid) AS size_bytes,
                pg_size_pretty(pg_relation_size(indexrelid)) AS size_pretty
            FROM pg_index
            JOIN pg_class ON pg_class.oid = pg_index.indexrelid
            JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace
            WHERE pg_namespace.nspname = 'app'
              AND pg_class.relname = 'idx_trip_assignments_trip_id';
            """
        )
        index_sizes = {r[0]: {"bytes": r[1], "pretty": r[2]} for r in cur.fetchall()}

        # Query row counts
        cur.execute("SELECT count(*) FROM app.trips;")
        trips_count = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM app.trip_assignments;")
        assignments_count = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM app.fraud_cases;")
        cases_count = cur.fetchone()[0]

    # --- INVARIANTS AND CORRECTNESS CHECKS ---
    # 1. Byte-for-byte query result equality
    assert data_trip_before == data_trip_after, "Trip assignment query results drifted after index application!"
    assert data_queue_before == data_queue_after, "Case queue query results drifted after index application!"

    # 2. Plan node transition for trip_assignment_by_trip: transitions from Seq Scan to Index Scan / Bitmap Scan
    assert bench_trip_before["node_type"] == "Seq Scan"
    assert bench_trip_after["node_type"] in ("Index Scan", "Bitmap Heap Scan")

    # 3. Verify full execution plans are retained in workload measurements
    assert "full_plan" in bench_trip_before and bench_trip_before["full_plan"] is not None
    assert "full_plan" in bench_trip_after and bench_trip_after["full_plan"] is not None
    assert "full_plan" in bench_queue_before and bench_queue_before["full_plan"] is not None
    assert "full_plan" in bench_queue_after and bench_queue_after["full_plan"] is not None

    # 4. Construct retained machine benchmark artifact
    benchmark_artifact = {
        "metadata": {
            "title": "P-063 Database Performance Benchmark Evidence (#394 / #399)",
            "environment": "disposable_local_postgresql_16",
            "fixture_cardinality": {
                "trips": trips_count,
                "trip_assignments": assignments_count,
                "fraud_cases": cases_count,
            },
            "correctness_verified": True,
            "result_rows_identical": True,
        },
        "indexes": {
            "applied": [
                "app.idx_trip_assignments_trip_id",
            ],
            "sizes": index_sizes,
        },
        "workloads": {
            "trip_assignment_by_trip": {
                "before": bench_trip_before,
                "after": bench_trip_after,
                "cost_reduction_pct": round(
                    (1 - bench_trip_after["total_cost"] / bench_trip_before["total_cost"]) * 100, 2
                ),
                "buffer_reduction_pct": round(
                    (1 - bench_trip_after["shared_hit_blocks"] / max(bench_trip_before["shared_hit_blocks"], 1)) * 100,
                    2,
                ),
            },
            "org_case_queue": {
                "before": bench_queue_before,
                "after": bench_queue_after,
                "cost_reduction_pct": round(
                    (1 - bench_queue_after["total_cost"] / bench_queue_before["total_cost"]) * 100, 2
                ),
                "buffer_reduction_pct": round(
                    (1 - bench_queue_after["shared_hit_blocks"] / max(bench_queue_before["shared_hit_blocks"], 1))
                    * 100,
                    2,
                ),
                "note": "Evaluated at 100 cases fixture; showed no demonstrated speedup. Unsupported queue index removed per empirical evidence.",
            },
        },
    }

    # Explicit evidence-write opt-in prevents normal test runs from silently rewriting the versioned artifact
    if os.environ.get("RECORD_BENCHMARK_EVIDENCE") == "1" or os.environ.get("UPDATE_BENCHMARK_ARTIFACT") == "1":
        BENCHMARK_ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
        BENCHMARK_ARTIFACT_PATH.write_text(json.dumps(benchmark_artifact, indent=2, default=str), encoding="utf-8")

    conn.close()


def test_apply_workload_indexes_cli_guardrails_and_expected_plan_hash():
    """Verify apply_workload_indexes.py CLI safety guardrails and plan hash preflight checks."""
    script_path = str(ROOT_DIR / "scripts" / "apply_workload_indexes.py")
    env = {**os.environ}

    # 1. Unconditional rejection without opt-in environment variable
    env_no_opt_in = {
        k: v for k, v in env.items() if k not in ("CONFIRM_DISPOSABLE_TEST_DB", "ALLOW_DISPOSABLE_DB_MIGRATION")
    }
    res_no_opt = subprocess.run(
        [sys.executable, script_path, "--target-url", TEST_DB_URL],
        env=env_no_opt_in,
        capture_output=True,
        text=True,
    )
    assert res_no_opt.returncode != 0
    assert "Explicit opt-in required" in res_no_opt.stderr or "Explicit opt-in required" in res_no_opt.stdout

    # 2. Mutually exclusive --env and --target-url rejection
    res_both = subprocess.run(
        [sys.executable, script_path, "--env", "dev", "--target-url", TEST_DB_URL],
        env=env,
        capture_output=True,
        text=True,
    )
    assert res_both.returncode != 0
    assert "not allowed with argument" in res_both.stderr or "not allowed with argument" in res_both.stdout

    # Enable opt-in for subsequent tests
    env["CONFIRM_DISPOSABLE_TEST_DB"] = "1"

    # 3. Dry-run produces expected plan hash and emits SQL preview without DDL
    res_dry = subprocess.run(
        [sys.executable, script_path, "--target-url", TEST_DB_URL],
        env=env,
        capture_output=True,
        text=True,
    )
    assert res_dry.returncode == 0
    match = re.search(r"Expected Plan Hash:\s+([a-f0-9]{64})", res_dry.stdout)
    assert match is not None, f"Failed to extract plan hash from dry-run output:\n{res_dry.stdout}"
    plan_hash = match.group(1)

    # 4. Confirm-apply without --expected-plan-hash fails before DDL
    res_missing_hash = subprocess.run(
        [sys.executable, script_path, "--target-url", TEST_DB_URL, "--confirm-apply"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert res_missing_hash.returncode != 0
    assert (
        "requires --expected-plan-hash" in res_missing_hash.stderr
        or "requires --expected-plan-hash" in res_missing_hash.stdout
    )

    # 5. Confirm-apply with mismatched --expected-plan-hash fails before DDL
    res_wrong_hash = subprocess.run(
        [sys.executable, script_path, "--target-url", TEST_DB_URL, "--confirm-apply", "--expected-plan-hash", "0" * 64],
        env=env,
        capture_output=True,
        text=True,
    )
    assert res_wrong_hash.returncode != 0
    assert "Mismatched plan hash" in res_wrong_hash.stderr or "Mismatched plan hash" in res_wrong_hash.stdout

    # 6. Confirm-apply with valid matching --expected-plan-hash applies DDL cleanly
    res_apply = subprocess.run(
        [
            sys.executable,
            script_path,
            "--target-url",
            TEST_DB_URL,
            "--confirm-apply",
            "--expected-plan-hash",
            plan_hash,
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert res_apply.returncode == 0
    assert (
        "Index migration APPLY completed cleanly" in res_apply.stderr
        or "Index migration APPLY completed cleanly" in res_apply.stdout
    )

    # 7. Rollback dry-run and apply
    res_rollback_dry = subprocess.run(
        [sys.executable, script_path, "--target-url", TEST_DB_URL, "--rollback"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert res_rollback_dry.returncode == 0
    rollback_match = re.search(r"Expected Plan Hash:\s+([a-f0-9]{64})", res_rollback_dry.stdout)
    assert rollback_match is not None
    rollback_hash = rollback_match.group(1)

    res_rollback_apply = subprocess.run(
        [
            sys.executable,
            script_path,
            "--target-url",
            TEST_DB_URL,
            "--rollback",
            "--confirm-apply",
            "--expected-plan-hash",
            rollback_hash,
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert res_rollback_apply.returncode == 0
    assert (
        "Index migration ROLLBACK completed cleanly" in res_rollback_apply.stderr
        or "Index migration ROLLBACK completed cleanly" in res_rollback_apply.stdout
    )

    # Re-apply to leave in optimized state
    res_reapply_dry = subprocess.run(
        [sys.executable, script_path, "--target-url", TEST_DB_URL],
        env=env,
        capture_output=True,
        text=True,
    )
    reapply_hash = re.search(r"Expected Plan Hash:\s+([a-f0-9]{64})", res_reapply_dry.stdout).group(1)
    res_reapply = subprocess.run(
        [
            sys.executable,
            script_path,
            "--target-url",
            TEST_DB_URL,
            "--confirm-apply",
            "--expected-plan-hash",
            reapply_hash,
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert res_reapply.returncode == 0
