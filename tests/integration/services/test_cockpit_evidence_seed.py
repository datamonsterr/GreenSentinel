"""Regression: cockpit evidence seed must populate columns whose default is an empty object."""

import os

import psycopg
import pytest

from scripts.enrich_demo_data import enrich_cockpit_evidence_only

pytestmark = pytest.mark.docker


def test_cockpit_seed_fills_default_empty_json_columns():
    url = os.environ["DATABASE_URL"]
    enrich_cockpit_evidence_only(url)
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT count(*) FROM app.fraud_cases
               WHERE id::text LIKE '018f2f4e-%%'
                 AND (cockpit_evidence = '{}'::jsonb OR workflow_draft = '{}'::jsonb)"""
        )
        assert cur.fetchone()[0] == 0
