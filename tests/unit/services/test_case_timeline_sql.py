"""SQL contract for the workflow timeline ribbon (issue #100, §3.3).

_load_case_timeline must query app.trip_events for the four lifecycle
milestones, order by occurred_at ASC, map labels, and return [] when the
case has no trip events.
"""

from datetime import datetime

from src.services.jev_precedent_service import TIMELINE_LABELS, _load_case_timeline


def _fake_conn(rows, captured):
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query, params=None):
            captured["query"] = query
            captured["params"] = params

        def fetchall(self):
            return rows

    class Conn:
        def cursor(self):
            return Cursor()

    return Conn()


def test_load_case_timeline_sql_content_ordering_and_empty_case():
    rows = [
        {"event_type": "dispatched", "occurred_at": datetime(2026, 10, 1, 14, 20, 0)},
        {"event_type": "driver_arriving", "occurred_at": datetime(2026, 10, 1, 14, 22, 15)},
        {"event_type": "cancelled_by_passenger", "occurred_at": datetime(2026, 10, 1, 14, 25, 0)},
        {"event_type": "dispute_opened", "occurred_at": datetime(2026, 10, 1, 14, 30, 0)},
    ]
    captured: dict = {}
    events = _load_case_timeline(_fake_conn(rows, captured), "case-1")

    query = captured["query"]
    assert "app.trip_events" in query
    assert "ORDER BY te.occurred_at ASC" in query
    for event_type in ("dispatched", "driver_arriving", "cancelled_by_passenger", "dispute_opened"):
        assert event_type in query
    assert captured["params"] == ("case-1",)

    assert [e.event_type for e in events] == [r["event_type"] for r in rows]
    assert [e.label for e in events] == [TIMELINE_LABELS[r["event_type"]] for r in rows]
    assert events[0].occurred_at.startswith("2026-10-01T14:20:00")

    assert _load_case_timeline(_fake_conn([], {}), "case-empty") == []
