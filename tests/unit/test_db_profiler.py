"""Unit tests for Database Performance Profiler service."""

from unittest.mock import MagicMock

import pytest

from src.services.db_profiler import (
    ALLOWLISTED_QUERIES,
    DatabaseProfiler,
    validate_disposable_database_url,
)


def test_profiler_disallows_arbitrary_or_mutating_sql():
    profiler = DatabaseProfiler()
    with pytest.raises(ValueError, match="not allowlisted|forbidden"):
        profiler.explain_query("DROP TABLE app.trips;", params=())

    with pytest.raises(ValueError, match="not allowlisted"):
        profiler.explain_query("SELECT * FROM secret_table;", params=())


def test_profiler_disallows_allowlist_bypass_via_query_key():
    """Providing query_key must NOT bypass the allowlist check or execute arbitrary SQL."""
    mock_conn = MagicMock()
    profiler = DatabaseProfiler(conn=mock_conn)

    # 1. Valid query_key but malicious mutating SQL
    with pytest.raises(ValueError, match="forbidden|does not match"):
        profiler.explain_query(
            "DELETE FROM app.fraud_cases;",
            params=(),
            query_key="trip_assignment_by_trip",
        )

    # 2. Valid query_key but mismatched SQL
    with pytest.raises(ValueError, match="does not match"):
        profiler.explain_query(
            "SELECT 1;",
            params=(),
            query_key="trip_assignment_by_trip",
        )

    # 3. Arbitrary/unknown query_key
    with pytest.raises(ValueError, match="not allowlisted"):
        profiler.explain_query(
            "SELECT 1;",
            params=(),
            query_key="non_existent_key",
        )

    # 4. Multi-statement injection attempt
    valid_sql = ALLOWLISTED_QUERIES["trip_assignment_by_trip"].sql
    injected_sql = f"{valid_sql}; DROP TABLE app.trips;"
    with pytest.raises(ValueError, match="does not match|forbidden"):
        profiler.explain_query(
            injected_sql,
            params=("00000000-0000-0000-0000-000000000001",),
            query_key="trip_assignment_by_trip",
        )

    # Ensure DB connection was never touched during validation failures
    mock_conn.cursor.assert_not_called()


def test_profiler_validates_parameter_counts():
    """Workload must reject wrong parameter count before connecting to DB."""
    mock_conn = MagicMock()
    profiler = DatabaseProfiler(conn=mock_conn)

    # trip_assignment_by_trip expects exactly 1 parameter
    with pytest.raises(ValueError, match="expects 1 parameter"):
        profiler.explain_workload("trip_assignment_by_trip", params=())

    with pytest.raises(ValueError, match="expects 1 parameter"):
        profiler.explain_workload("trip_assignment_by_trip", params=("p1", "p2"))

    mock_conn.cursor.assert_not_called()


def test_profiler_timeout_validation():
    """Timeout must accept positive bounded integer only."""
    with pytest.raises(ValueError, match="positive bounded integer"):
        DatabaseProfiler(timeout_ms=-100)

    with pytest.raises(ValueError, match="positive bounded integer"):
        DatabaseProfiler(timeout_ms=0)

    with pytest.raises(ValueError, match="positive bounded integer"):
        DatabaseProfiler(timeout_ms=1000000)

    with pytest.raises(ValueError, match="positive bounded integer"):
        DatabaseProfiler(timeout_ms=5.5)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="positive bounded integer"):
        DatabaseProfiler(timeout_ms=True)  # type: ignore[arg-type]


def test_profiler_timeout_and_readonly_safeguards():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    profiler = DatabaseProfiler(conn=mock_conn, timeout_ms=3000)
    query_key = "trip_assignment_by_trip"

    mock_cursor.fetchone.return_value = [
        [
            {
                "Plan": {
                    "Node Type": "Index Scan",
                    "Total Cost": 8.25,
                    "Actual Rows": 1,
                    "Shared Hit Blocks": 3,
                    "Shared Read Blocks": 0,
                },
                "Execution Time": 0.045,
                "Planning Time": 0.12,
            }
        ]
    ]

    result = profiler.explain_workload(query_key, params=("00000000-0000-0000-0000-000000000001",))

    # Assert timeouts and search_path were set within transaction
    executed_statements = [call[0][0] for call in mock_cursor.execute.call_args_list]
    assert any("SET TRANSACTION READ ONLY" in s for s in executed_statements)
    assert any("SET LOCAL statement_timeout = 3000" in s for s in executed_statements)
    assert any("SET LOCAL search_path" in s for s in executed_statements)
    assert any("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)" in s for s in executed_statements)

    # Rollback transaction must be invoked explicitly with force_rollback=True
    mock_conn.transaction.assert_called_once_with(force_rollback=True)

    assert result["node_type"] == "Index Scan"
    assert result["total_cost"] == 8.25
    assert result["execution_time_ms"] == 0.045
    assert result["shared_hit_blocks"] == 3


def test_profiler_redacts_credentials_in_summary():
    profiler = DatabaseProfiler()
    raw_info = {
        "host": "secret.proxy.rlwy.net",
        "user": "postgres",
        "password": "supersecretpassword123",
        "dbname": "railway",
        "conninfo": "postgresql://postgres:mysecretpass@db.example.com:5432/mydb",
    }
    sanitized = profiler.sanitize_connection_info(raw_info)
    assert sanitized["password"] == "[REDACTED]"
    assert "mysecretpass" not in str(sanitized)
    assert "supersecretpassword123" not in str(sanitized)
    assert "[REDACTED]" in sanitized["conninfo"]
    assert sanitized["user"] == "postgres"
    assert sanitized["host"] == "secret.proxy.rlwy.net"


def test_disposable_database_validator_rejection_rules(monkeypatch):
    """Integration target validator must reject non-loopback, non-test DBs, and missing opt-ins."""
    # 1. Reject without opt-in flag
    monkeypatch.delenv("CONFIRM_DISPOSABLE_TEST_DB", raising=False)
    monkeypatch.delenv("ALLOW_DISPOSABLE_DB_MIGRATION", raising=False)
    valid_url = "postgresql://postgres:postgrespassword@localhost:5432/test_greensentinel_bench"
    with pytest.raises(ValueError, match="Explicit opt-in required"):
        validate_disposable_database_url(valid_url)

    # Set opt-in for subsequent tests
    monkeypatch.setenv("CONFIRM_DISPOSABLE_TEST_DB", "1")

    # 2. Reject remote Railway proxy
    with pytest.raises(ValueError, match="loopback"):
        validate_disposable_database_url("postgresql://postgres:secret@roundhouse.proxy.rlwy.net:1234/test_bench")

    # 3. Reject non-loopback LAN IP
    with pytest.raises(ValueError, match="loopback"):
        validate_disposable_database_url("postgresql://postgres:secret@192.168.1.55:5432/test_bench")

    # 4. Reject production/staging/dev database names on localhost
    with pytest.raises(ValueError, match="'test_' prefix"):
        validate_disposable_database_url("postgresql://postgres:pass@localhost:5432/railway")

    with pytest.raises(ValueError, match="'test_' prefix"):
        validate_disposable_database_url("postgresql://postgres:pass@127.0.0.1:5432/production")

    with pytest.raises(ValueError, match="'test_' prefix"):
        validate_disposable_database_url("postgresql://postgres:pass@localhost:5432/dev")

    with pytest.raises(ValueError, match="'test_' prefix"):
        validate_disposable_database_url("postgresql://postgres:pass@127.0.0.1:5432/staging")

    # 5. Valid loopback test DB passes
    assert validate_disposable_database_url(valid_url) == valid_url
    ipv4_loopback = "postgresql://postgres:postgrespassword@127.0.0.1:5432/test_disposable"
    assert validate_disposable_database_url(ipv4_loopback) == ipv4_loopback


def test_redact_dsn_password_handles_spaces_and_quotes():
    """Redaction must handle quoted keyword passwords with spaces and backslashes."""
    from src.services.db_profiler import redact_dsn_password

    # Single-quoted password with spaces
    s1 = "host=localhost port=5432 password='my secret pass' user=postgres dbname=app"
    r1 = redact_dsn_password(s1)
    assert "my secret pass" not in r1
    assert "secret" not in r1
    assert "pass'" not in r1
    assert "password=[REDACTED]" in r1

    # Double-quoted password with spaces and escaped characters
    s2 = 'host=localhost password="pass with \\"quotes\\" & spaces" user=postgres'
    r2 = redact_dsn_password(s2)
    assert "pass with" not in r2
    assert "quotes" not in r2
    assert "password=[REDACTED]" in r2

    # Mixed-case password keyword
    s3 = "host=localhost PassWord='TopSecretKey987!' dbname=test"
    r3 = redact_dsn_password(s3)
    assert "TopSecretKey987!" not in r3
    assert "[REDACTED]" in r3


def test_redact_dsn_password_url_query_parameters():
    """Redaction must handle passwords and tokens in URL query strings and URI userinfo."""
    from src.services.db_profiler import redact_dsn_password

    # Password query parameter in URL
    u1 = "postgresql://localhost:5432/mydb?password=secret_in_query&sslmode=require"
    r1 = redact_dsn_password(u1)
    assert "secret_in_query" not in r1
    assert "password=[REDACTED]" in r1

    # Secret token in query parameter
    u2 = "postgresql://localhost:5432/mydb?auth_token=super_secret_token_123"
    r2 = redact_dsn_password(u2)
    assert "super_secret_token_123" not in r2
    assert "[REDACTED]" in r2

    # Userinfo password
    u3 = "postgresql://app_user:p%40ss_word%21@db.host.internal:5432/production"
    r3 = redact_dsn_password(u3)
    assert "p%40ss_word%21" not in r3
    assert "[REDACTED]" in r3


def test_sanitize_connection_info_omits_raw_dsn_and_mixed_case():
    """sanitize_connection_info must use allowlisted safe metadata keys and redact raw DSNs."""
    profiler = DatabaseProfiler()
    raw_info = {
        "host": "db.internal.net",
        "port": 5432,
        "dbname": "app_db",
        "user": "app_user",
        "TARGET_DATABASE_URL": "postgresql://usr:secret_dsn_pass@db.internal.net:5432/app_db",
        "conninfo": "host=db.internal.net password='literal secret with spaces' user=app_user",
        "Secret_Auth_Token": "tok_xyz_9999",
        "arbitrary_custom_secret": "raw_sensitive_literal_42",
    }
    sanitized = profiler.sanitize_connection_info(raw_info)

    # Allowlisted safe metadata preserved
    assert sanitized["host"] == "db.internal.net"
    assert sanitized["port"] == 5432
    assert sanitized["dbname"] == "app_db"
    assert sanitized["user"] == "app_user"

    # Raw secrets completely omitted / redacted
    assert "secret_dsn_pass" not in str(sanitized)
    assert "literal secret with spaces" not in str(sanitized)
    assert "tok_xyz_9999" not in str(sanitized)
    assert "raw_sensitive_literal_42" not in str(sanitized)

    # Sensitive keys replaced
    assert "[REDACTED" in sanitized["TARGET_DATABASE_URL"]
    assert "[REDACTED" in sanitized["conninfo"]
    assert sanitized["Secret_Auth_Token"] == "[REDACTED]"
    assert sanitized["arbitrary_custom_secret"] == "[REDACTED]"


def test_profiler_rejects_caller_active_transaction():
    """Profiler must reject an already open active transaction without rolling it back."""
    import psycopg.pq

    mock_conn = MagicMock()
    mock_conn.info.transaction_status = psycopg.pq.TransactionStatus.INTRANS
    profiler = DatabaseProfiler(conn=mock_conn)

    with pytest.raises(RuntimeError, match="idle|active transaction"):
        profiler.explain_workload("trip_assignment_by_trip", params=("00000000-0000-0000-0000-000000000001",))

    # Crucial: Must NOT call rollback on caller's connection!
    mock_conn.rollback.assert_not_called()
