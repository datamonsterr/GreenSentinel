from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.services.kb_service import KbService
from src.services.kb_store import MemoryStore

ORG = "org-1"


def who(role, pid):
    return SimpleNamespace(id=pid, organization_id=ORG, roles=frozenset({role}))


ANALYST = who("fraud_analyst", "u-analyst")
ANALYST2 = who("analyst", "u-analyst2")
SENIOR = who("senior_analyst", "u-senior")
ADMIN = who("admin", "u-admin")
VH = who("manager", "u-vh")
DRIVER = who("driver", "u-driver")

CASES = [
    {"case_id": f"c{i}", "params": {"fare_vnd": 100000, "stationary_duration_s": 100 * i, "trips_today": 9}}
    for i in range(1, 7)
]


@pytest.fixture()
def svc():
    return KbService(MemoryStore(cases=CASES))


MOTIVE = {
    "beneficiary": "driver",
    "policy": "MILESTONE-1",
    "formula": "=IF(trips_today+1>=milestone_trips, milestone_bonus_vnd-trip_cost_vnd, 0)",
}


def motive(svc, code="MOT_MILESTONE", body=None, actor=ANALYST):
    return svc.create_object(
        actor, type="motive", code=code, name="Thưởng mốc", scope={"region": "HN"}, body=body or MOTIVE
    )


def to_trial(svc, obj, actor=ANALYST):
    svc.submit(actor, obj["id"])
    return svc.start_trial(actor, obj["id"])


def test_create_is_draft_v1_and_audited(svc):
    o = motive(svc)
    assert (o["status"], o["version"], o["author_id"]) == ("draft", 1, "u-analyst")
    assert any(a["action"] == "kb.object.create" for a in svc.store.audit_log)


def test_duplicate_code_conflict(svc):
    motive(svc)
    with pytest.raises(HTTPException) as e:
        motive(svc)
    assert e.value.status_code == 409


def test_driver_and_vh_cannot_author_or_read(svc):
    with pytest.raises(HTTPException) as e:
        motive(svc, actor=DRIVER)
    assert e.value.status_code == 403
    with pytest.raises(HTTPException):
        svc.list_objects(VH)


def test_submit_blocked_on_invalid_formula(svc):
    o = motive(svc, body={**MOTIVE, "formula": "=nope+1"})
    with pytest.raises(HTTPException) as e:
        svc.submit(ANALYST, o["id"])
    assert e.value.status_code == 422
    assert e.value.detail["errors"][0]["code"] == "unknown_param"


def test_full_lifecycle_four_eyes(svc):
    o = motive(svc)
    o = svc.submit(ANALYST, o["id"])
    assert o["status"] == "ready_for_test"
    o = svc.start_trial(ANALYST, o["id"])
    assert o["status"] == "trial" and o["replay"]["cases_total"] == len(CASES)
    for k in ("matched", "changed_scenario", "not_computable", "est_turns"):
        assert k in o["replay"]
    with pytest.raises(HTTPException) as e:  # author cannot approve own work
        svc.publish(ANALYST, o["id"])
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:  # analyst2 lacks approver role
        svc.publish(ANALYST2, o["id"])
    assert e.value.status_code == 403
    admin_author = motive(svc, code="MOT_B", actor=ADMIN)
    to_trial(svc, admin_author, ADMIN)
    with pytest.raises(HTTPException) as e:  # admin authored: admin cannot also approve
        svc.publish(ADMIN, admin_author["id"])
    assert e.value.status_code == 403
    pub = svc.publish(ADMIN, o["id"])
    assert pub["status"] == "published" and pub["approver_id"] == "u-admin"
    assert svc.get_published(ORG, "motive", "MOT_MILESTONE")["id"] == o["id"]
    assert [x["code"] for x in svc.list_published(ORG, "motive")] == ["MOT_MILESTONE"]
    actions = [a["action"] for a in svc.store.audit_log]
    assert {"kb.object.submit", "kb.object.trial", "kb.object.publish"} <= set(actions)


def test_draft_not_visible_to_agents(svc):
    motive(svc)
    assert svc.get_published(ORG, "motive", "MOT_MILESTONE") is None
    assert svc.list_published(ORG, "motive") == []


def test_new_version_supersedes_and_rollback(svc):
    v1 = motive(svc)
    to_trial(svc, v1)
    svc.publish(ADMIN, v1["id"])
    v2 = svc.clone_object(ANALYST, v1["id"])
    assert v2["version"] == 2 and v2["status"] == "draft"
    svc.update_object(ANALYST, v2["id"], body={**MOTIVE, "formula": "=trip_cost_vnd*2"}, reason="more")
    to_trial(svc, v2)
    svc.publish(SENIOR, v2["id"])
    assert svc.get_published(ORG, "motive", "MOT_MILESTONE")["version"] == 2
    assert svc.get_object(ANALYST, v1["id"])["status"] == "retired"
    back = svc.rollback(ADMIN, v2["id"], reason="bad")
    assert back["version"] == 1 and back["status"] == "published"
    assert svc.get_object(ANALYST, v2["id"])["status"] == "retired"
    assert svc.get_published(ORG, "motive", "MOT_MILESTONE")["version"] == 1


def test_rollback_requires_previous_and_approver(svc):
    v1 = motive(svc)
    to_trial(svc, v1)
    svc.publish(ADMIN, v1["id"])
    with pytest.raises(HTTPException) as e:
        svc.rollback(ADMIN, v1["id"], reason="because")
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        svc.rollback(ANALYST, v1["id"], reason="because")
    assert e.value.status_code == 403


def test_retire_takes_effect_immediately(svc):
    v1 = motive(svc)
    to_trial(svc, v1)
    svc.publish(ADMIN, v1["id"])
    svc.retire(ANALYST, v1["id"], reason="obsolete")
    assert svc.get_published(ORG, "motive", "MOT_MILESTONE") is None


def test_edit_only_before_trial(svc):
    v1 = motive(svc)
    svc.update_object(ANALYST, v1["id"], name="Renamed")
    to_trial(svc, v1)
    with pytest.raises(HTTPException) as e:
        svc.update_object(ANALYST, v1["id"], name="x")
    assert e.value.status_code == 409


def test_edit_ready_for_test_returns_to_draft(svc):
    v1 = motive(svc)
    svc.submit(ANALYST, v1["id"])
    out = svc.update_object(ANALYST, v1["id"], body={**MOTIVE, "formula": "=trip_cost_vnd"})
    assert out["status"] == "draft"


def test_low_computability_gate_requires_override(svc):
    body = {**MOTIVE, "formula": "=gps_km/billed_km"}  # no case provides these params
    o = motive(svc, code="MOT_GATE", body=body)
    to_trial(svc, o)
    assert svc.get_object(ANALYST, o["id"])["replay"]["gate_passed"] is False
    with pytest.raises(HTTPException) as e:
        svc.publish(ADMIN, o["id"])
    assert e.value.status_code == 422
    out = svc.publish(ADMIN, o["id"], override_reason="Reviewed manually with ops")
    assert out["status"] == "published" and out["override_reason"]


def test_behavior_and_scenario_and_workflow_flow(svc):
    b = svc.create_object(
        ANALYST,
        type="behavior",
        code="BHV_STILL",
        name="Đứng yên",
        scope={},
        body={"description": "still", "signals": ["stationary_duration_s"], "condition": "=stationary_duration_s>=300"},
    )
    to_trial(svc, b)
    assert svc.get_object(ANALYST, b["id"])["replay"]["matched"] == 4  # 300..600 of 100..600
    w = svc.create_object(
        ANALYST,
        type="workflow",
        code="WF_STILL",
        name="Cuốc ảo",
        scope={},
        body={
            "ask_first": ["Bạn có chở khách không?"],
            "steps": [{"question": "Mã ticket?", "tool": "identify_behavior", "branch": ""}],
            "stop_condition": "n_max",
            "help_condition": "no_tool",
        },
    )
    to_trial(svc, w)
    s = svc.create_object(
        ANALYST,
        type="scenario",
        code="SCN_1",
        name="Kịch bản",
        scope={},
        body={
            "motive_code": "MOT_MILESTONE",
            "behavior_code": "BHV_STILL",
            "reason": "Có khách thật",
            "workflow_code": "WF_STILL",
        },
    )
    svc.submit(ANALYST, s["id"])
    svc.start_trial(ANALYST, s["id"])
    with pytest.raises(HTTPException) as e:  # references are not published
        svc.publish(ADMIN, s["id"])
    assert e.value.status_code == 422
    for x in (b, w):
        svc.publish(ADMIN, x["id"])
    m = motive(svc)
    to_trial(svc, m)
    svc.publish(ADMIN, m["id"])
    assert svc.publish(ADMIN, s["id"])["status"] == "published"


def test_workflow_validation(svc):
    bad = svc.create_object(
        ANALYST,
        type="workflow",
        code="WF_BAD",
        name="x",
        scope={},
        body={"ask_first": [], "steps": [{"question": "Mức phạt là 500k", "tool": "launch_missiles"}]},
    )
    with pytest.raises(HTTPException) as e:
        svc.submit(ANALYST, bad["id"])
    codes = {x["code"] for x in e.value.detail["errors"]}
    assert {"unknown_tool", "forbidden_content"} <= codes


def test_preview_on_cases(svc):
    o = motive(svc)
    out = svc.preview(ANALYST, o["id"], case_ids=["c1", "c2"])
    assert [r["case_id"] for r in out["results"]] == ["c1", "c2"]
    assert out["results"][0]["value"] == 38000 and "trips_today" in out["results"][0]["params_used"]
    assert "milestone_trips" in out["results"][0]["assumed"]  # policy constants fall back to catalogue defaults
    out = svc.preview(ANALYST, o["id"], params={"milestone_trips": 9, "trip_cost_vnd": 0})
    assert out["results"][0]["value"] == 50000 and "milestone_trips" not in out["results"][0]["assumed"]
    bad = motive(svc, code="MOT_NOCASE", body={**MOTIVE, "formula": "=gps_km"})
    assert svc.preview(ANALYST, bad["id"])["results"][0]["error"]["code"] == "missing_value"


def test_proposals_accept_edit_reject(svc):
    p1 = svc.create_proposal(
        ORG,
        source="policy_analysis",
        type="motive",
        title="Thưởng mốc cuốc vẫy",
        payload={"code": "MOT_HAIL", "name": "Hail", "scope": {}, "body": MOTIVE},
        source_excerpt="Điều 3",
        mapping="reuse",
        similarity=0.8,
        matched_code="MOT_MILESTONE",
        created_by="analysis-agent",
    )
    out = svc.accept_proposal(ANALYST, p1["id"])
    assert out["proposal"]["status"] == "accepted"
    assert out["object"]["status"] == "ready_for_test" and out["object"]["code"] == "MOT_HAIL"
    p2 = svc.create_proposal(
        ORG,
        source="help_reply",
        type="workflow",
        title="Bước tra ticket",
        payload={"code": "WF_X", "name": "x", "scope": {}, "body": {"ask_first": [], "steps": []}},
        created_by="driver-agent",
    )
    out = svc.edit_proposal(
        ANALYST,
        p2["id"],
        payload={"code": "WF_X", "name": "x2", "scope": {}, "body": {"ask_first": ["a"], "steps": []}},
    )
    assert out["proposal"]["status"] == "edited" and out["object"]["name"] == "x2"
    p3 = svc.create_proposal(ORG, source="monitoring", type="behavior", title="t", payload={}, created_by="monitor")
    with pytest.raises(HTTPException) as e:
        svc.reject_proposal(ANALYST, p3["id"], reason_code="", note="")
    assert e.value.status_code == 422
    with pytest.raises(HTTPException):
        svc.reject_proposal(ANALYST, p3["id"], reason_code="bogus", note="")
    out = svc.reject_proposal(ANALYST, p3["id"], reason_code="duplicate", note="đã có")
    assert out["status"] == "rejected" and out["reason_code"] == "duplicate"
    with pytest.raises(HTTPException) as e:  # decided once
        svc.reject_proposal(ANALYST, p3["id"], reason_code="other", note="")
    assert e.value.status_code == 409
    assert [p["status"] for p in svc.list_proposals(ANALYST, status="pending")] == []


def test_proposal_cannot_publish(svc):
    p = svc.create_proposal(
        ORG,
        source="manual",
        type="motive",
        title="t",
        payload={"code": "MOT_P", "name": "p", "scope": {}, "body": MOTIVE},
        created_by="agent",
    )
    obj = svc.accept_proposal(ANALYST, p["id"])["object"]
    assert obj["status"] == "ready_for_test"
    assert svc.get_published(ORG, "motive", "MOT_P") is None


def test_documents_indexing_status_and_similarity(svc, monkeypatch):
    monkeypatch.delenv("EMBEDDINGS_API_KEY", raising=False)
    d = svc.create_document(
        ANALYST,
        name="Chính sách thưởng",
        code="POL-1",
        text="thưởng mốc chuyến 10 cuốc",
        filename="a.txt",
        content_type="text/plain",
        size_bytes=30,
        effective_from="2026-11-01",
        region="HN",
    )
    assert d["indexing_status"] == "embeddings_not_configured"
    assert svc.list_documents(ANALYST)[0]["code"] == "POL-1"
    with pytest.raises(HTTPException) as e:
        svc.create_document(ANALYST, name="", code="", text="", filename="a.txt", content_type="x", size_bytes=1)
    assert e.value.status_code == 422


def test_similar_uses_scorer(svc):
    motive(svc)
    out = svc.similar(ANALYST, "thưởng mốc milestone bonus", type="motive")
    assert out and out[0]["code"] == "MOT_MILESTONE" and 0 < out[0]["similarity"] <= 1


def test_registry_lists_agents_and_knowledge_counts(svc):
    reg = svc.registry(ANALYST)
    ids = {a["id"] for a in reg["agents"]}
    assert {"driver_agent", "policy_analysis_agent", "monitoring_agent"} <= ids
    d = next(a for a in reg["agents"] if a["id"] == "driver_agent")
    assert d["model"] and d["tools"] and d["memory_layers"] and d["instruction_version"]
    assert "motive" in d["knowledge_types"]
    assert "published_counts" in reg


def test_seed_idempotent(svc):
    a = svc.seed_demo(ADMIN)
    b = svc.seed_demo(ADMIN)
    assert a["created"] > 0 and b["created"] == 0
    assert svc.list_published(ORG, "motive")


def test_org_isolation(svc):
    o = motive(svc)
    other = SimpleNamespace(id="x", organization_id="org-2", roles=frozenset({"admin"}))
    with pytest.raises(HTTPException) as e:
        svc.get_object(other, o["id"])
    assert e.value.status_code == 404
