from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_principal
from src.api.knowledge_routes import router
from src.services.agent_config_service import AgentConfigService, get_agent_config_service
from src.services.kb_service import KbService, get_kb_service
from src.services.kb_store import MemoryStore

ORG = "org-1"
PEOPLE = {
    "analyst": SimpleNamespace(id="u-a", organization_id=ORG, roles=frozenset({"fraud_analyst"})),
    "admin": SimpleNamespace(id="u-b", organization_id=ORG, roles=frozenset({"admin"})),
    "driver": SimpleNamespace(id="u-d", organization_id=ORG, roles=frozenset({"driver"})),
}
MOTIVE = {"formula": "=fare_vnd*0.1"}


@pytest.fixture()
def api():
    store = MemoryStore(cases=[{"case_id": "c1", "params": {"fare_vnd": 100000}}])
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    who = {"p": PEOPLE["analyst"]}
    app.dependency_overrides[require_principal] = lambda: who["p"]
    app.dependency_overrides[get_kb_service] = lambda: KbService(store)
    app.dependency_overrides[get_agent_config_service] = lambda: AgentConfigService(store)
    client = TestClient(app)

    def as_(name):
        who["p"] = PEOPLE[name]
        return client

    return as_


def test_formula_validate_endpoint(api):
    c = api("analyst")
    assert c.post("/api/v1/knowledge/formula/validate", json={"formula": "=fare_vnd*2"}).json()["ok"] is True
    r = c.post("/api/v1/knowledge/formula/validate", json={"formula": "=zzz"}).json()
    assert r["ok"] is False and r["errors"][0]["code"] == "unknown_param"
    assert any(p["code"] == "fare_vnd" for p in c.get("/api/v1/knowledge/parameters").json()["items"])


def test_object_flow_two_users(api):
    c = api("analyst")
    r = c.post("/api/v1/knowledge/objects", json={"type": "motive", "code": "MOT_X", "name": "x", "body": MOTIVE})
    assert r.status_code == 201
    oid = r.json()["id"]
    assert c.post(f"/api/v1/knowledge/objects/{oid}/submit").json()["status"] == "ready_for_test"
    assert c.post(f"/api/v1/knowledge/objects/{oid}/trial").json()["replay"]["cases_total"] == 1
    assert c.post(f"/api/v1/knowledge/objects/{oid}/publish").status_code == 403  # analyst is not an approver
    adm = api("admin")
    assert adm.post(f"/api/v1/knowledge/objects/{oid}/publish").json()["status"] == "published"
    assert adm.get("/api/v1/knowledge/objects", params={"type": "motive", "status": "published"}).json()["items"][0]["code"] == "MOT_X"
    assert adm.get("/api/v1/knowledge/objects/motive/MOT_X/versions").json()["items"][0]["version"] == 1


def test_driver_blocked(api):
    c = api("driver")
    assert c.get("/api/v1/knowledge/objects").status_code == 403
    assert c.get("/api/v1/agent-config").status_code == 403


def test_config_and_kill_switch_endpoints(api):
    adm = api("admin")
    r = adm.put("/api/v1/agent-config/n_max", json={"value": 4, "reason": "tighten"})
    assert r.status_code == 200 and r.json()["value"] == 4
    assert adm.put("/api/v1/agent-config/n_max", json={"value": 0, "reason": "bad"}).status_code == 422
    assert adm.post("/api/v1/agent-config/kill-switch", json={"enabled": True, "reason": "go live"}).json()["value"] is True
    hist = adm.get("/api/v1/agent-config/history/list", params={"key": "n_max"}).json()["items"]
    assert hist[0]["new_value"] == 4
    assert adm.post(f"/api/v1/agent-config/history/{hist[0]['id']}/revert", json={"reason": "undo it"}).json()["value"] == 6
    cfg = adm.get("/api/v1/agent-config").json()
    assert {i["key"] for i in cfg["items"]} >= {"n_max", "k_dynamic", "explain_agent_enabled"}


def test_documents_and_proposals_endpoints(api):
    c = api("analyst")
    r = c.post("/api/v1/knowledge/documents", json={"name": "P", "code": "P-1", "text": "bonus policy"})
    assert r.status_code == 201 and r.json()["indexing_status"] == "embeddings_not_configured"
    assert c.post("/api/v1/knowledge/documents", json={"name": "", "code": ""}).status_code == 422
    p = c.post("/api/v1/knowledge/proposals", json={"type": "motive", "title": "t", "payload": {"code": "MOT_P", "name": "p", "body": MOTIVE}})
    assert p.status_code == 201
    pid = p.json()["id"]
    assert c.post(f"/api/v1/knowledge/proposals/{pid}/reject", json={"reason_code": "bogus"}).status_code == 422
    assert c.post(f"/api/v1/knowledge/proposals/{pid}/accept").json()["object"]["status"] == "ready_for_test"
    assert c.get("/api/v1/knowledge/proposals", params={"status": "accepted"}).json()["items"][0]["id"] == pid
