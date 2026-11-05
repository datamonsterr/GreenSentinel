"""External database prerequisites for service-backed test cases."""

import psycopg
import pytest


def require_database(url: str, *, required: bool) -> None:
    """Probe before creating test state; keep an optional unavailable DB explicit."""
    available = False
    try:
        with psycopg.connect(url, connect_timeout=3) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT to_regclass('app.fraud_cases')")
                row = cursor.fetchone()
                available = bool(row and row[0])
    except psycopg.Error:
        pass
    if not available:
        if required:
            pytest.fail("Required integration database/schema is unavailable", pytrace=False)
        pytest.skip("Optional integration database/schema is unavailable")
