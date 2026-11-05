"""Draft writes preserve tenant boundaries, revisions and recorded workflow events."""

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from src.models.schemas import WorkflowDraftRequest
from src.services.case_service import CaseService


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(CaseService, "_load_seed_data", lambda self: None)
    svc = CaseService()
    monkeypatch.setattr(svc, "_get_db_connection", lambda: None)
    svc._cases = {
        "case-demo": {"id": "case-demo", "organization_id": "org-a", "status": "ready", "created_at": datetime.now(UTC)}
    }
    return svc


@pytest.mark.asyncio
async def test_draft_round_trip_and_no_duplicate_event_on_retry(service):
    saved = await service.save_workflow_draft(
        "case-demo",
        WorkflowDraftRequest(text="Review recorded GPS", expected_version=0),
        analyst_id="analyst-a",
        organization_id="org-a",
    )
    assert saved.version == 1
    assert saved.updated_by == "analyst-a"
    assert (await service.get_workflow_draft("case-demo", organization_id="org-a")).text == "Review recorded GPS"
    retried = await service.save_workflow_draft(
        "case-demo",
        WorkflowDraftRequest(text=saved.text, expected_version=0),
        analyst_id="analyst-a",
        organization_id="org-a",
    )
    assert retried.version == 1
    assert len(service._cases["case-demo"]["workflow_trace"]["timeline"]) == 1
    assert service._cases["case-demo"]["workflow_trace"]["timeline"][0]["event_type"] == "workflow_draft_saved"


@pytest.mark.asyncio
async def test_draft_rejects_stale_version_and_preserves_text(service):
    await service.save_workflow_draft(
        "case-demo", WorkflowDraftRequest(text="first", expected_version=0), analyst_id="a", organization_id="org-a"
    )
    with pytest.raises(HTTPException) as err:
        await service.save_workflow_draft(
            "case-demo", WorkflowDraftRequest(text="stale", expected_version=0), analyst_id="b", organization_id="org-a"
        )
    assert err.value.status_code == 409
    assert (await service.get_workflow_draft("case-demo", organization_id="org-a")).text == "first"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["resolved", "dismissed", "auto_dismissed", "suspended"])
async def test_terminal_drafts_are_read_only(service, status):
    service._cases["case-demo"]["status"] = status
    with pytest.raises(HTTPException) as err:
        await service.save_workflow_draft(
            "case-demo", WorkflowDraftRequest(text="edit"), analyst_id="a", organization_id="org-a"
        )
    assert err.value.status_code == 409


@pytest.mark.asyncio
async def test_draft_cross_org_read_and_write_are_not_found(service):
    for operation in (
        service.get_workflow_draft("case-demo", organization_id="org-b"),
        service.save_workflow_draft(
            "case-demo", WorkflowDraftRequest(text="edit"), analyst_id="a", organization_id="org-b"
        ),
    ):
        with pytest.raises(HTTPException) as err:
            await operation
        assert err.value.status_code == 404
    assert "workflow_draft" not in service._cases["case-demo"]
