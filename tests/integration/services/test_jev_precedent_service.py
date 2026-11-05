"""Unit and integration tests for JevPrecedentService (POC v2 Precedent Workflow Mining)."""

import pytest

from src.models.schemas import WorkflowTrace
from src.services.jev_precedent_service import (
    JevPrecedentService,
    get_jev_precedent_service,
)
from src.services.precedent_repository import SCORE_SEMANTICS, PrecedentPersistenceError


@pytest.fixture
def precedent_service(monkeypatch: pytest.MonkeyPatch) -> JevPrecedentService:
    service = get_jev_precedent_service()
    monkeypatch.setattr(service, "_get_db_connection", lambda: None)
    return service


def test_list_precedents_seeded(precedent_service: JevPrecedentService):
    precedents = precedent_service.list_precedents()
    assert len(precedents) >= 5
    ids = [p.id for p in precedents]
    assert "018f2f4e-9100-7000-8000-000000000001" in ids
    assert "018f2f4e-9100-7000-8000-000000000002" in ids


def test_get_precedent_by_id(precedent_service: JevPrecedentService):
    p = precedent_service.get_precedent("018f2f4e-9100-7000-8000-000000000001")
    assert p is not None
    assert p.violation_code == "ERR-02"
    assert p.claim_type == "traffic_gridlock"
    assert p.verdict == "exonerated"
    assert len(p.workflow_trace.agent_tools_called) >= 1
    assert p.workflow_trace.agent_tools_called[0].tool_name == "corroborate_traffic_conditions"
    assert len(p.workflow_trace.related_policies) >= 1
    assert p.workflow_trace.final_decision is not None
    assert p.workflow_trace.final_decision.verdict == "exonerated"


def test_list_precedents_with_filters(precedent_service: JevPrecedentService):
    err05_items = precedent_service.list_precedents(violation_code="ERR-05")
    assert len(err05_items) >= 1
    for item in err05_items:
        assert item.violation_code == "ERR-05"

    gridlock_items = precedent_service.list_precedents(claim_type="traffic_gridlock")
    assert len(gridlock_items) >= 2
    for item in gridlock_items:
        assert item.claim_type == "traffic_gridlock"


@pytest.mark.asyncio
async def test_match_precedent_traffic_gridlock(precedent_service: JevPrecedentService):
    res = await precedent_service.match_precedent(
        case_id="case-test-match-01",
        claim_type="traffic_gridlock",
        driver_statement="Đoạn đường Kim Mã Liễu Giai bị tắc nghẽn nghiêm trọng, xe di chuyển dưới 5km/h",
        violation_code="ERR-02",
        telemetry_summary={"corroborated": True, "ratio": 2.7, "observed_speed": 2.1},
    )
    assert res.has_match is True
    assert res.top_match is not None
    assert res.top_match.precedent_id in (
        "018f2f4e-9100-7000-8000-000000000001",
        "018f2f4e-9100-7000-8000-000000000002",
    )
    assert res.top_match.similarity_score >= 0.80
    assert res.top_match.score_semantics == SCORE_SEMANTICS
    assert res.top_match.provenance.eligible_for_reuse is False
    assert len(res.top_match.matching_factors) >= 2
    assert "corroborate_traffic_conditions" in res.top_match.recommended_procedure


@pytest.mark.asyncio
async def test_match_precedent_gps_issue(precedent_service: JevPrecedentService):
    res = await precedent_service.match_precedent(
        case_id="case-test-match-02",
        claim_type="gps_issue",
        driver_statement="Vào hầm B2 trung tâm thương mại Vincom Royal City bị mất sóng GPS và 4G",
        violation_code="ERR-05",
        telemetry_summary={"corroborated": False, "ratio": 1.0, "observed_speed": 0.0},
    )
    assert res.has_match is True
    assert res.top_match is not None
    assert "018f2f4e-9100-7000-8000-000000000003" in [c.precedent_id for c in res.all_candidates]


def test_synthesize_workflow_trace(precedent_service: JevPrecedentService):
    trace = precedent_service.synthesize_workflow_trace(
        case_id="case-synth-01",
        decision_data={
            "verdict": "exonerated",
            "penalty_amount": 0,
            "rationale": "Chấp thuận giải trình sự cố kẹt xe thực tế từ GPS.",
            "decided_by": "anl-001",
            "decided_at": "2026-09-26T21:00:00Z",
        },
    )
    assert isinstance(trace, WorkflowTrace)
    assert trace.agent_tools_called == []
    assert trace.related_policies == []
    assert trace.final_decision is not None
    assert trace.final_decision.verdict == "exonerated"
    assert trace.final_decision.decided_by == "anl-001"
    assert trace.final_decision.explicit_human_approval is False


def test_apply_precedent_procedure(precedent_service: JevPrecedentService):
    procedure = precedent_service.apply_precedent_procedure(
        case_id="case-app-01",
        precedent_id="018f2f4e-9100-7000-8000-000000000001",
    )
    assert procedure["case_id"] == "case-app-01"
    assert procedure["precedent_id"] == "018f2f4e-9100-7000-8000-000000000001"
    assert procedure["recommended_verdict"] == "exonerated"
    assert procedure["recommended_penalty_amount"] == 0
    assert "corroborate_traffic_conditions" in procedure["recommended_tools"]
    assert "[Áp dụng quy trình án lệ" in procedure["recommended_rationale"]


@pytest.mark.asyncio
async def test_publish_precedent_workflow_requires_authoritative_records(
    precedent_service: JevPrecedentService,
):
    trace = precedent_service.synthesize_workflow_trace(
        case_id="case-pub-01",
        decision_data={
            "verdict": "exonerated",
            "penalty_amount": 0,
            "rationale": "Test publish precedent",
            "decided_by": "anl-001",
            "decided_at": "2026-09-26T21:00:00Z",
        },
    )
    with pytest.raises(PrecedentPersistenceError, match="Tenant and signing analyst"):
        await precedent_service.publish_precedent_workflow(
            case_id="case-pub-01",
            title="Án lệ thử nghiệm kiểm thử tự động",
            workflow_trace=trace,
            verdict="exonerated",
            district="Cau Giay",
            confidence_score=0.99,
        )
