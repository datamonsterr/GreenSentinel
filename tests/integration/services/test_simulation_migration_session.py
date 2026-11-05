"""Docker init runs each migration in a fresh SQL session with default search_path."""

import os
from pathlib import Path

import psycopg
import pytest


def test_submission_migration_uses_app_schema_from_fresh_session():
    url = os.getenv("TEST_SIMULATION_DATABASE_URL")
    if not url:
        pytest.skip("TEST_SIMULATION_DATABASE_URL must name a disposable migrated database")
    root = Path(__file__).resolve().parents[3]
    migration = root / "db/migrations/20261015130000_tester_publish_submissions.sql"
    with psycopg.connect(url) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SET search_path = public")
                cur.execute(migration.read_text())
                cur.execute("SELECT to_regclass('public.test_run_submissions')")
                assert cur.fetchone()[0] is None
                cur.execute("SELECT to_regclass('app.test_run_submissions')")
                assert cur.fetchone()[0] is not None
        finally:
            conn.rollback()
