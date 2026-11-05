"""Database performance profiler and index inventory service.

Provides safe, read-only EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) profiling
for allowlisted queries with bound parameters, bounded statement timeouts,
and zero data mutation or live session disruption.
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import psycopg
import psycopg.pq

logger = logging.getLogger("db_profiler")

DEFAULT_STATEMENT_TIMEOUT_MS = 5000
MIN_STATEMENT_TIMEOUT_MS = 100
MAX_STATEMENT_TIMEOUT_MS = 60000

DANGEROUS_SQL_PATTERN = re.compile(
    r"\b(DROP|DELETE|INSERT|UPDATE|ALTER|TRUNCATE|GRANT|REVOKE|CREATE|EXECUTE)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AllowlistedQuery:
    key: str
    description: str
    sql: str
    example_param_names: tuple[str, ...]


ALLOWLISTED_QUERIES: dict[str, AllowlistedQuery] = {
    "org_case_queue": AllowlistedQuery(
        key="org_case_queue",
        description="Active fraud cases sorted by priority tier and score within an organization",
        sql="""
            SELECT c.id, c.status, c.dispute_status, c.priority_tier, c.priority_score, c.created_at
            FROM app.fraud_cases c
            WHERE c.organization_id = %s
              AND LOWER(c.status) = LOWER(%s)
            ORDER BY c.priority_tier ASC, c.priority_score DESC, c.created_at DESC
            LIMIT %s OFFSET %s;
        """,
        example_param_names=("organization_id", "status", "limit", "offset"),
    ),
    "trip_assignment_by_trip": AllowlistedQuery(
        key="trip_assignment_by_trip",
        description="Retrieve assignment details for a trip",
        sql="""
            SELECT id, trip_id, driver_id, vehicle_id, state, accepted_at, started_at, ended_at
            FROM app.trip_assignments
            WHERE trip_id = %s;
        """,
        example_param_names=("trip_id",),
    ),
    "telemetry_points_by_assignment": AllowlistedQuery(
        key="telemetry_points_by_assignment",
        description="Retrieve ordered GPS telemetry breadcrumbs for an assignment",
        sql="""
            SELECT event_id, occurred_at, speed_mps, bearing_deg, accuracy_m, anomaly_type
            FROM app.telemetry_points
            WHERE assignment_id = %s
            ORDER BY occurred_at ASC;
        """,
        example_param_names=("assignment_id",),
    ),
    "case_by_assignment": AllowlistedQuery(
        key="case_by_assignment",
        description="Lookup case linked to a trip assignment",
        sql="""
            SELECT id, organization_id, status, suspected_category, priority_tier
            FROM app.fraud_cases
            WHERE assignment_id = %s;
        """,
        example_param_names=("assignment_id",),
    ),
    "driver_lookup_by_external_ref": AllowlistedQuery(
        key="driver_lookup_by_external_ref",
        description="Lookup driver by organization and external ref",
        sql="""
            SELECT id, organization_id, account_status
            FROM app.drivers
            WHERE organization_id = %s AND external_ref = %s;
        """,
        example_param_names=("organization_id", "external_ref"),
    ),
}


def redact_dsn_password(conninfo_or_url: str) -> str:
    """Safely redact passwords, tokens, and credentials from URLs, conninfo strings, or exceptions."""
    if not isinstance(conninfo_or_url, str):
        return str(conninfo_or_url)

    text = conninfo_or_url

    # 1. URI userinfo password: scheme://user:password@host
    text = re.sub(
        r"([a-zA-Z][a-zA-Z0-9+.-]*://[^/:@\s]+:)(?:[^\s/@]+)(@)",
        r"\1[REDACTED]\2",
        text,
    )

    # 2. URI query parameters: ?password=... or &password=... or &token=... or &auth_token=... etc.
    text = re.sub(
        r"([?&](?:pass(?:word)?|pwd|secret|token|auth(?:_token)?)=)(?:[^&#\s]*)",
        r"\1[REDACTED]",
        text,
        flags=re.IGNORECASE,
    )

    # 3. Keyword conninfo: password='...' or password="..." or password=...
    # Handles single quotes, double quotes, backslash-escapes, and spaces inside quotes
    pattern = re.compile(
        r"""(?i)(?:\b|(?<=_))((?:(?:postgres_|pg)?pass(?:word)?|pwd|secret|token|auth(?:_token)?))\s*=\s*(?:'[^'\\]*(?:\\.[^'\\]*)*'|"[^"\\]*(?:\\.[^"\\]*)*"|[^\s;]+)"""
    )
    text = pattern.sub(r"\1=[REDACTED]", text)
    return text


def validate_disposable_database_url(url: str) -> str:
    """Validate that target database URL strictly points to an isolated local disposable database.

    Enforces:
    1. Explicit opt-in via CONFIRM_DISPOSABLE_TEST_DB=1 or ALLOW_DISPOSABLE_DB_MIGRATION=1.
    2. Host strictly resolves to local loopback (localhost, 127.0.0.1, ::1).
    3. Database name begins with 'test_' prefix.
    4. Rejects any Railway, remote, production, staging, or dev shared instances.
    """
    opt_in = (
        os.environ.get("CONFIRM_DISPOSABLE_TEST_DB") == "1" or os.environ.get("ALLOW_DISPOSABLE_DB_MIGRATION") == "1"
    )
    if not opt_in:
        raise ValueError(
            "Explicit opt-in required: set CONFIRM_DISPOSABLE_TEST_DB=1 or ALLOW_DISPOSABLE_DB_MIGRATION=1 "
            "to run against disposable test database."
        )

    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    loopback_hosts = {"localhost", "127.0.0.1", "::1"}

    if hostname not in loopback_hosts:
        raise ValueError(
            f"Target host '{hostname}' is not a local loopback interface (localhost, 127.0.0.1, ::1). "
            "Remote or non-loopback connections are forbidden for disposable testing."
        )

    dbname = parsed.path.lstrip("/").lower()
    if not dbname.startswith("test_"):
        raise ValueError(
            f"Database name '{dbname}' lacks required 'test_' prefix for disposable testing. "
            "Execution is blocked to prevent accidental mutation of non-test databases."
        )

    # Double check for dangerous words
    forbidden_terms = {"railway", "production", "staging", "dev"}
    # If dbname is test_railway or test_dev, check if it's strictly a test prefix
    # But dbname must never be equal to any live shared name
    if dbname in forbidden_terms:
        raise ValueError(f"Database name '{dbname}' matches a live environment name.")

    return url


class DatabaseProfiler:
    """Service for safe profiling and index auditing on Postgres databases."""

    def __init__(self, conn: Any | None = None, timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS):
        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int):
            raise ValueError("timeout_ms must be a positive bounded integer between 100 and 60000 ms.")
        if not (MIN_STATEMENT_TIMEOUT_MS <= timeout_ms <= MAX_STATEMENT_TIMEOUT_MS):
            raise ValueError(
                f"timeout_ms must be a positive bounded integer between "
                f"{MIN_STATEMENT_TIMEOUT_MS} and {MAX_STATEMENT_TIMEOUT_MS} ms, got {timeout_ms}."
            )
        self.conn = conn
        self.timeout_ms = timeout_ms

    @staticmethod
    def sanitize_connection_info(info: dict[str, Any]) -> dict[str, Any]:
        """Redact sensitive credentials using allowlisted safe metadata keys and whole DSN redaction."""
        sanitized: dict[str, Any] = {}
        safe_keys = {"target", "host", "port", "dbname", "database", "schema", "user", "username", "sslmode"}
        sensitive_key_fragments = ("pass", "pwd", "secret", "token", "auth", "key", "credential")
        raw_dsn_keys = (
            "conninfo",
            "target_url",
            "database_url",
            "migration_database_url",
            "target_database_url",
            "url",
        )

        for key, val in info.items():
            key_str = str(key)
            key_lower = key_str.lower()

            if any(k == key_lower for k in raw_dsn_keys):
                if isinstance(val, str) and ("password=" in val.lower() or "://" in val):
                    sanitized[key_str] = redact_dsn_password(val)
                else:
                    sanitized[key_str] = "[REDACTED_DSN]"
            elif any(frag in key_lower for frag in sensitive_key_fragments):
                sanitized[key_str] = "[REDACTED]"
            elif key_lower in safe_keys:
                if isinstance(val, str) and ("password=" in val.lower() or "://" in val):
                    sanitized[key_str] = redact_dsn_password(val)
                else:
                    sanitized[key_str] = val
            else:
                sanitized[key_str] = "[REDACTED]"

        return sanitized

    def get_allowlisted_query(self, query_key: str) -> AllowlistedQuery:
        if query_key not in ALLOWLISTED_QUERIES:
            raise ValueError(f"Query key '{query_key}' is not allowlisted.")
        return ALLOWLISTED_QUERIES[query_key]

    def explain_workload(self, query_key: str, params: tuple[Any, ...]) -> dict[str, Any]:
        query_def = self.get_allowlisted_query(query_key)
        return self.explain_query(query_def.sql, params=params, query_key=query_key)

    def explain_query(self, sql_text: str, params: tuple[Any, ...], query_key: str | None = None) -> dict[str, Any]:
        """Execute EXPLAIN ANALYZE on an allowlisted query within a read-only rolled-back transaction."""
        # 1. Enforce no mutating or dangerous SQL keywords
        if DANGEROUS_SQL_PATTERN.search(sql_text):
            raise ValueError("Mutating or dangerous SQL statements are strictly forbidden during profiling.")

        # 2. Check for multi-statement execution attempts
        stripped_sql = sql_text.strip().rstrip(";")
        if ";" in stripped_sql:
            raise ValueError("Multi-statement SQL execution is strictly forbidden.")

        normalized_input = " ".join(stripped_sql.split())

        # 3. Allowlist validation
        if query_key is not None:
            if query_key not in ALLOWLISTED_QUERIES:
                raise ValueError(f"Query key '{query_key}' is not allowlisted.")
            expected_sql = " ".join(ALLOWLISTED_QUERIES[query_key].sql.strip().rstrip(";").split())
            if normalized_input != expected_sql:
                raise ValueError("Supplied SQL does not match the allowlisted query definition.")
        else:
            matching = [
                k
                for k, q in ALLOWLISTED_QUERIES.items()
                if " ".join(q.sql.strip().rstrip(";").split()) == normalized_input
            ]
            if not matching:
                raise ValueError("Arbitrary SQL is not allowlisted for profiling.")
            query_key = matching[0]

        # 4. Parameter count validation
        expected_param_count = len(ALLOWLISTED_QUERIES[query_key].example_param_names)
        if len(params) != expected_param_count:
            raise ValueError(f"Query '{query_key}' expects {expected_param_count} parameter(s), got {len(params)}.")

        if not self.conn:
            raise RuntimeError("Database connection not provided to profiler.")

        explain_sql = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {stripped_sql}"

        # Check if caller has an active transaction; profiler requires IDLE connection
        conn_info = getattr(self.conn, "info", None)
        if conn_info is not None and hasattr(conn_info, "transaction_status"):
            status = conn_info.transaction_status
            if isinstance(status, (psycopg.pq.TransactionStatus, int)):
                if status != psycopg.pq.TransactionStatus.IDLE:
                    raise RuntimeError(
                        f"Database connection is not in IDLE transaction status (status={status}). "
                        "DatabaseProfiler requires an idle connection to avoid clobbering an existing active transaction."
                    )

        orig_autocommit = getattr(self.conn, "autocommit", False)

        try:
            if hasattr(self.conn, "transaction"):
                with self.conn.transaction(force_rollback=True):
                    with self.conn.cursor() as cur:
                        cur.execute("SET TRANSACTION READ ONLY;")
                        cur.execute("SET LOCAL search_path = app, extensions, public;")
                        cur.execute(f"SET LOCAL statement_timeout = {int(self.timeout_ms)};")
                        cur.execute(f"SET LOCAL lock_timeout = {min(int(self.timeout_ms), 5000)};")
                        cur.execute(explain_sql, params)
                        row = cur.fetchone()
                        if not row or not row[0]:
                            raise RuntimeError("Failed to obtain EXPLAIN execution plan.")

                        plan_payload = row[0][0]
                        root_plan = plan_payload.get("Plan", {})
            else:
                try:
                    with self.conn.cursor() as cur:
                        cur.execute("SET TRANSACTION READ ONLY;")
                        cur.execute("SET LOCAL search_path = app, extensions, public;")
                        cur.execute(f"SET LOCAL statement_timeout = {int(self.timeout_ms)};")
                        cur.execute(f"SET LOCAL lock_timeout = {min(int(self.timeout_ms), 5000)};")
                        cur.execute(explain_sql, params)
                        row = cur.fetchone()
                        if not row or not row[0]:
                            raise RuntimeError("Failed to obtain EXPLAIN execution plan.")

                        plan_payload = row[0][0]
                        root_plan = plan_payload.get("Plan", {})
                finally:
                    if hasattr(self.conn, "rollback"):
                        self.conn.rollback()
        finally:
            if hasattr(self.conn, "autocommit") and self.conn.autocommit != orig_autocommit:
                self.conn.autocommit = orig_autocommit

        return {
            "query_key": query_key,
            "node_type": root_plan.get("Node Type"),
            "total_cost": root_plan.get("Total Cost"),
            "actual_rows": root_plan.get("Actual Rows"),
            "shared_hit_blocks": root_plan.get("Shared Hit Blocks", 0),
            "shared_read_blocks": root_plan.get("Shared Read Blocks", 0),
            "planning_time_ms": plan_payload.get("Planning Time"),
            "execution_time_ms": plan_payload.get("Execution Time"),
            "full_plan": plan_payload,
        }

    @contextmanager
    def _read_transaction(self):
        """Execute read-only catalog/inspection queries while leaving connection in IDLE state."""
        if not self.conn:
            raise RuntimeError("Database connection not provided.")
        conn = self.conn
        if hasattr(conn, "transaction"):
            with conn.transaction():
                yield conn
        else:
            try:
                yield conn
            finally:
                if not getattr(conn, "autocommit", False) and hasattr(conn, "commit"):
                    conn.commit()

    def check_tenancy_invariants(self) -> dict[str, int]:
        """Perform verified tenant isolation audit queries without data mutation."""
        with self._read_transaction() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM app.organizations;")
                orgs_count = cur.fetchone()[0]

                cur.execute("SELECT count(*) FROM app.trips WHERE organization_id IS NULL;")
                null_trips = cur.fetchone()[0]

                cur.execute(
                    """
                    SELECT count(*)
                    FROM app.trip_assignments a
                    JOIN app.trips t ON a.trip_id = t.id
                    JOIN app.drivers d ON a.driver_id = d.id
                    WHERE t.organization_id <> d.organization_id;
                    """
                )
                cross_org = cur.fetchone()[0]

                return {
                    "organizations": orgs_count,
                    "null_org_trips": null_trips,
                    "cross_org_linkages": cross_org,
                }

    def preflight_schema_check(
        self, required_tables: list[str], required_columns: dict[str, list[str]]
    ) -> dict[str, Any]:
        """Read-only preflight check verifying that required tables and columns exist in schema."""
        with self._read_transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'app' AND table_name = ANY (%s);
                    """,
                    (required_tables,),
                )
                found_tables = {r[0] for r in cur.fetchall()}
                missing_tables = [t for t in required_tables if t not in found_tables]

                missing_columns: dict[str, list[str]] = {}
                for tbl, cols in required_columns.items():
                    if tbl in found_tables:
                        cur.execute(
                            """
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_schema = 'app' AND table_name = %s AND column_name = ANY (%s);
                            """,
                            (tbl, cols),
                        )
                        found_cols = {r[0] for r in cur.fetchall()}
                        tbl_missing = [c for c in cols if c not in found_cols]
                        if tbl_missing:
                            missing_columns[tbl] = tbl_missing

                return {
                    "valid": len(missing_tables) == 0 and len(missing_columns) == 0,
                    "missing_tables": missing_tables,
                    "missing_columns": missing_columns,
                }

    def fetch_index_inventory(self, schema_name: str = "app") -> list[dict[str, Any]]:
        """Fetch all indexes in the given schema."""
        with self._read_transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT schemaname, tablename, indexname, indexdef
                    FROM pg_indexes
                    WHERE schemaname = %s
                    ORDER BY tablename, indexname;
                    """,
                    (schema_name,),
                )
                rows = cur.fetchall()
                return [
                    {
                        "schema": r[0] if isinstance(r, (list, tuple)) else r["schemaname"],
                        "table": r[1] if isinstance(r, (list, tuple)) else r["tablename"],
                        "index_name": r[2] if isinstance(r, (list, tuple)) else r["indexname"],
                        "definition": r[3] if isinstance(r, (list, tuple)) else r["indexdef"],
                    }
                    for r in rows
                ]

    def audit_unindexed_foreign_keys(self, schema_name: str = "app") -> list[dict[str, Any]]:
        """Detect foreign key constraints whose leading column lacks a supporting index."""
        with self._read_transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        tc.table_schema,
                        tc.table_name,
                        kcu.column_name,
                        ccu.table_schema AS foreign_table_schema,
                        ccu.table_name AS foreign_table_name,
                        ccu.column_name AS foreign_column_name,
                        tc.constraint_name
                    FROM
                        information_schema.table_constraints AS tc
                        JOIN information_schema.key_column_usage AS kcu
                          ON tc.constraint_name = kcu.constraint_name
                          AND tc.table_schema = kcu.table_schema
                        JOIN information_schema.constraint_column_usage AS ccu
                          ON ccu.constraint_name = tc.constraint_name
                          AND ccu.table_schema = tc.table_schema
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                      AND tc.table_schema = %s
                    ORDER BY tc.table_name, kcu.column_name;
                    """,
                    (schema_name,),
                )
                fks = cur.fetchall()

                cur.execute(
                    """
                    SELECT
                        t.relname AS table_name,
                        a.attname AS column_name
                    FROM pg_index x
                    JOIN pg_class t ON t.oid = x.indrelid
                    JOIN pg_namespace n ON n.oid = t.relnamespace
                    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(x.indkey)
                    WHERE n.nspname = %s
                      AND x.indkey[0] = a.attnum;
                    """,
                    (schema_name,),
                )
                indexed_leading_cols = set((r[0], r[1]) for r in cur.fetchall())

                unindexed = []
                for row in fks:
                    tbl = row[1]
                    col = row[2]
                    if (tbl, col) not in indexed_leading_cols:
                        unindexed.append(
                            {
                                "table": tbl,
                                "column": col,
                                "foreign_table": row[4],
                                "foreign_column": row[5],
                                "constraint_name": row[6],
                            }
                        )
                return unindexed
