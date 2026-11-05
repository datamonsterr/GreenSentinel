import json
from collections import Counter
from unittest.mock import MagicMock

from scripts import seed_database
from scripts.generate_seed_sql import generate_sql
from scripts.generate_synthetic_data import generate_synthetic_dataset


def test_seed_is_reproducible_with_unique_named_drivers_and_two_honest_route_legs():
    first = generate_synthetic_dataset()
    second = generate_synthetic_dataset()
    assert first == second
    assert len({d["display_name"] for d in first["drivers"]}) == 20
    assert len({a["driver_id"] for a in first["trip_assignments"]}) == 20
    assert set(Counter(r["assignment_id"] for r in first["route_snapshots"]).values()) == {2}
    for row in first["route_snapshots"]:
        assert row["leg"] in {"pickup", "destination"}
        assert row["provider"] == "osrm"
        assert row["provenance"]["dataset_version"] == "road-v1"
        assert row["provenance"]["status"] == "ok"
        assert row["provenance"]["is_shortest_path"] is False
    for rows in first.values():
        if isinstance(rows, list) and rows and "id" in rows[0]:
            assert len({row["id"] for row in rows}) == len(rows)


def test_both_seed_writers_persist_names_and_legs(tmp_path, monkeypatch):
    data = generate_synthetic_dataset()
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps(data))
    sql_file = tmp_path / "seed.sql"
    generate_sql(seed, sql_file)
    sql = sql_file.read_text()
    assert all(d["display_name"] in sql for d in data["drivers"])
    assert "assignment_id, leg, calculated_at" in sql
    assert "ON CONFLICT (assignment_id, leg) DO NOTHING" in sql
    assert "ON CONFLICT (assignment_id, leg) DO UPDATE" not in sql
    conn = MagicMock()
    monkeypatch.setattr(seed_database, "get_connection", lambda: conn)
    seed_database.import_data(seed)
    calls = conn.cursor.return_value.__enter__.return_value.execute.call_args_list
    many_calls = conn.cursor.return_value.__enter__.return_value.executemany.call_args_list
    drivers = [call for call in calls if "INSERT INTO app.drivers " in call.args[0]]
    assert len(drivers) == 20
    assert all(
        "display_name" in call.args[0] and data["drivers"][i]["display_name"] in call.args[1]
        for i, call in enumerate(drivers)
    )
    routes_many = [call for call in many_calls if "INSERT INTO app.route_snapshots " in call.args[0]]
    if routes_many:
        param_rows = routes_many[0].args[1]
        assert len(param_rows) == 200
        assert all(row[2] in {"pickup", "destination"} for row in param_rows)
    else:
        routes = [call for call in calls if "INSERT INTO app.route_snapshots " in call.args[0]]
        assert len(routes) == 200
        assert all(
            "leg" in call.args[0] and row["leg"] in call.args[1] for call, row in zip(routes, data["route_snapshots"])
        )
