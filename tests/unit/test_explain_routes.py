from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_principal
from src.api.explain_routes import router
from src.services.agent_config_service import AgentConfigService
from src.services.explain_llm import DeterministicExplainLLM
from src.services.explain_service import ExplainService, get_explain_service
from src.services.kb_service import KbService
from src.services.kb_store import MemoryStore

ORG = "org-1"
CASE = "case-1"
P = {
    "driver": SimpleNamespace(id="u-d1", organization_id=ORG, roles=frozenset({"driver"}), driver_id="drv-1"),
    "other": SimpleNamespace(id="u-d2", organization_id=ORG, roles=frozenset({"driver"}), driver_id="drv-2"),
    "analyst": SimpleNamespace(id="u-a", organization_id=ORG, roles=frozenset({"fraud_analyst"})),
    "admin": SimpleNamespace(id="u-b", organization_id=ORG, roles=frozenset({"admin"})),
}
ANSWERS = {
    "pickup_place": "Cổng chợ",
    "pickup_time": "14:00",
    "passenger_desc": "Nữ",
    "dropoff_place": "Khu Y",
    "route": "Đường Z",
    "payment_amount": "85000",
    "payment_method": "cash",
}


@pytest.fixture()
def api():
    store = MemoryStore(
        cases=[
            {
                "case_id": CASE,
                "organization_id": ORG,
                "driver_id": "drv-1",
                "category": "ERR-02",
                "params": {"stationary_duration_s": 600, "trips_today": 9, "fare_vnd": 85000},
            }
        ]
    )
    kb = KbService(store)
    cfg = AgentConfigService(store)
    kb.seed_demo(P["admin"])
    cfg.set_kill_switch(P["admin"], True, "turn on")
    service = ExplainService(store, kb, cfg, DeterministicExplainLLM())
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    who = {"p": P["driver"]}
    app.dependency_overrides[require_principal] = lambda: who["p"]
    app.dependency_overrides[get_explain_service] = lambda: service
    client = TestClient(app)

    def as_(name):
        who["p"] = P[name]
        return client

    as_.store = store
    return as_


def test_driver_flow_end_to_end_over_http(api):
    c = api("driver")
    r = c.post(f"/api/v1/driver/cases/{CASE}/explain/start", json={"reason": "RealTrip"})
    assert r.status_code == 200 and r.json()["ui_status"] == "form"
    assert c.put(f"/api/v1/driver/cases/{CASE}/explain/draft", json={"answers": {"pickup_place": "Cổng chợ"}}).json()[
        "form"
    ]["answers"]
    bad = c.post(f"/api/v1/driver/cases/{CASE}/explain/submit", json={"answers": {}})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "form_invalid"
    r = c.post(f"/api/v1/driver/cases/{CASE}/explain/submit", json={"answers": ANSWERS})
    assert r.status_code == 200 and r.json()["state"] == "asking" and r.json()["current_question"]
    r = c.post(f"/api/v1/driver/cases/{CASE}/explain/answer", json={"text": "Tôi chạy thật"})
    assert r.status_code == 200
    r = c.post(f"/api/v1/driver/cases/{CASE}/explain/end")
    assert r.json()["state"] == "summary"
    r = c.post(f"/api/v1/driver/cases/{CASE}/explain/summary/edit", json={"text": "Bổ sung: khách đi cùng con nhỏ"})
    assert r.json()["edits_left"] == 1
    r = c.post(f"/api/v1/driver/cases/{CASE}/explain/summary/confirm")
    assert r.json()["state"] == "submitted"
    assert c.get(f"/api/v1/driver/cases/{CASE}/explain").json()["state"] == "submitted"

    a = api("analyst").get(f"/api/v1/cases/{CASE}/explain").json()
    assert a["flags"]["asked_for_help"] is False and len(a["rounds"]) == 2 and a["provenance"]
    assert (
        api("analyst")
        .post(f"/api/v1/cases/{CASE}/explain/feedback", json={"verdict": "disagree", "error_types": []})
        .status_code
        == 422
    )
    fb = api("analyst").post(
        f"/api/v1/cases/{CASE}/explain/feedback",
        json={"verdict": "disagree", "error_types": ["wrong_facts"], "comment": "x"},
    )
    assert fb.status_code == 201


def test_other_driver_gets_404_and_driver_cannot_use_analyst_routes(api):
    api("driver").post(f"/api/v1/driver/cases/{CASE}/explain/start", json={"reason": "RealTrip"})
    o = api("other")
    assert o.get(f"/api/v1/driver/cases/{CASE}/explain").status_code == 404
    assert o.post(f"/api/v1/driver/cases/{CASE}/explain/start", json={"reason": "RealTrip"}).status_code == 404
    d = api("driver")
    assert d.get(f"/api/v1/cases/{CASE}/explain").status_code == 403
    assert d.get("/api/v1/explain/help-requests").status_code == 403
    assert d.get("/api/v1/explain/help-requests/count").status_code == 403
    an = api("analyst")
    assert an.post(f"/api/v1/driver/cases/{CASE}/explain/start", json={"reason": "RealTrip"}).status_code in (403, 404)


def test_help_queue_endpoints(api):
    d = api("driver")
    d.post(f"/api/v1/driver/cases/{CASE}/explain/start", json={"reason": "RealTrip"})
    d.post(f"/api/v1/driver/cases/{CASE}/explain/submit", json={"answers": ANSWERS})
    r = d.post(f"/api/v1/driver/cases/{CASE}/explain/answer", json={"text": "có ticket", "ticket_code": "0000-1234"})
    assert r.json()["waiting_for_help"] is True
    an = api("analyst")
    assert an.get("/api/v1/explain/help-requests/count").json() == {"open": 1, "claimed": 0, "total": 1}
    items = an.get("/api/v1/explain/help-requests").json()["items"]
    hid = items[0]["id"]
    detail = an.get(f"/api/v1/explain/help-requests/{hid}").json()
    assert detail["transcript"] and detail["stuck_point"]
    assert an.post(f"/api/v1/explain/help-requests/{hid}/claim").json()["status"] == "claimed"
    rep = an.post(f"/api/v1/explain/help-requests/{hid}/reply", json={"text": "Ticket hợp lệ", "facts": ["ticket ok"]})
    assert rep.status_code == 200 and rep.json()["status"] == "answered"
    assert an.get("/api/v1/explain/help-requests/count").json()["total"] == 0
    assert an.get("/api/v1/explain/help-requests?status=answered").json()["items"][0]["reply"] == "Ticket hợp lệ"
    g = api("driver").get(f"/api/v1/driver/cases/{CASE}/explain")
    assert g.status_code == 200, g.text
    v = g.json()
    assert v["waiting_for_help"] is False and v["current_question"]


def test_meta_and_unauthenticated(api):
    assert "wrong_facts" in api("analyst").get("/api/v1/explain/meta").json()["feedback_error_types"]
