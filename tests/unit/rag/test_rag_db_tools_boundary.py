from datetime import UTC, datetime
from uuid import uuid4

from src.rag.db_tools import get_case_list_priority, get_driver_history


class Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, sql, params=()):
        self.sql.append((sql, params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows[0] if len(rows) == 1 and isinstance(rows[0], list) else rows


class Connection:
    def __init__(self, rows):
        self.cursor_obj = Cursor(rows)
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True


class Service:
    def __init__(self, connection):
        self.connection = connection

    def _get_db_connection(self):
        return self.connection


def test_driver_history_maps_live_row_and_preserves_missing_fare():
    trip_id = uuid4()
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    connection = Connection(
        [
            {
                "trip_id": trip_id,
                "timestamp": timestamp,
                "service_type": "car",
                "trip_status": "completed",
                "assignment_state": "completed",
                "fare_minor": None,
                "stall_duration_sec": None,
                "anomaly_flag": None,
            }
        ]
    )
    result = get_driver_history(str(uuid4()), service=Service(connection))
    item = result["items"][0]
    assert result["source"] == "database"
    assert item["trip_id"] == str(trip_id)
    assert item["timestamp"] == timestamp.isoformat()
    assert item["fare_vnd"] is None
    assert item["stall_duration_sec"] is None
    assert connection.closed


def test_case_queue_uses_database_rows_without_cache_fallback():
    case_id = uuid4()
    connection = Connection(
        [
            {"total": 1},
            [
                {
                    "id": case_id,
                    "priority_tier": 1,
                    "priority_score": 10,
                    "created_at": datetime(2026, 1, 1, tzinfo=UTC),
                }
            ],
        ]
    )
    result = get_case_list_priority(service=Service(connection))
    assert result["source"] == "database"
    assert result["items"][0]["id"] == str(case_id)
    assert "c.priority_tier" in connection.cursor_obj.sql[-1][0]
