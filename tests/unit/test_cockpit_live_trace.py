"""Active traces retain persisted draft events and original trip milestones."""

from unittest.mock import MagicMock

from src.models.schemas import WorkflowTimelineEvent
from src.services.jev_precedent_service import JevPrecedentService


def test_live_trace_loads_persisted_events_without_a_finalized_precedent(monkeypatch):
    service = object.__new__(JevPrecedentService)
    service.case_service = MagicMock(_case_aliases={})
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = {
        "workflow_trace": {
            "timeline": [
                {
                    "event_type": "workflow_draft_saved",
                    "occurred_at": "2026-10-19T12:00:00+00:00",
                    "label": "Draft saved",
                }
            ]
        },
    }
    monkeypatch.setattr(service, "_get_db_connection", lambda: conn)
    monkeypatch.setattr("src.services.jev_precedent_service.get_finalized_by_case", lambda *a, **kw: None)
    monkeypatch.setattr(
        "src.services.jev_precedent_service._load_case_timeline",
        lambda *a: [WorkflowTimelineEvent(event_type="dispatched", occurred_at="2026-10-19T11:00:00+00:00")],
    )
    trace = service.get_workflow_trace("case-id", organization_id="org-a")
    assert [event.event_type for event in trace.timeline] == ["dispatched", "workflow_draft_saved"]
    params = conn.cursor.return_value.__enter__.return_value.execute.call_args.args[1]
    assert params == ("case-id", "org-a")
    conn.close.assert_called_once()
