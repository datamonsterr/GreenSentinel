import json
from unittest.mock import MagicMock

import pytest

from scripts.enrich_demo_data import enrich_telemetry, has_preserved_road_dataset
from scripts.generate_seed_sql import generate_sql
from scripts.generate_synthetic_data import generate_synthetic_dataset
from scripts.migrate_postgres import seed_database_from_json


def _road_seed(tmp_path):
    seed = generate_synthetic_dataset()
    seed["manifest"] = {"dataset_version": "road-v1"}
    seed["route_snapshots"][0]["provenance"]["dataset_version"] = "road-v1"
    path = tmp_path / "road.json"
    path.write_text(json.dumps(seed), encoding="utf-8")
    return path


def test_versioned_sql_never_replaces_existing_route(tmp_path):
    output = tmp_path / "seed.sql"
    generate_sql(_road_seed(tmp_path), output)
    sql = output.read_text(encoding="utf-8")

    assert "ON CONFLICT (assignment_id, leg) DO NOTHING" in sql
    assert "DO UPDATE SET provider = EXCLUDED.provider" not in sql


def test_enrichment_detects_road_evidence_and_does_not_write():
    cur = MagicMock()
    cur.fetchone.return_value = (True,)

    assert has_preserved_road_dataset(cur) is True
    assert enrich_telemetry(cur) == 0
    assert not any("DELETE FROM app.telemetry_points" in call.args[0] for call in cur.execute.call_args_list)
    assert not any("DELETE FROM app.ingest_events" in call.args[0] for call in cur.execute.call_args_list)


def test_versioned_seed_import_is_not_skipped_when_passengers_exist(tmp_path, monkeypatch):
    seed = _road_seed(tmp_path)
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (10,)
    imported = []
    monkeypatch.setattr("scripts.seed_database.import_data", lambda path, conn: imported.append((path, conn)))

    seed_database_from_json(conn, seed)

    assert imported == [(seed, conn)]


def test_import_restores_external_autocommit_after_rollback(tmp_path):
    seed = tmp_path / "invalid.json"
    seed.write_text("{}", encoding="utf-8")
    conn = MagicMock()
    conn.autocommit = True

    with pytest.raises(KeyError):
        from scripts.seed_database import import_data

        import_data(seed, conn=conn)

    assert conn.autocommit is True
    conn.rollback.assert_called_once()
