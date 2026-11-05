"""Issue #236 HTTP seams against real CaseService's isolated test storage.

This proves API contracts and read-after-write, not durable PostgreSQL storage.
The manual runbook requires restart/DB evidence separately.
"""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.auth import Principal, require_principal
from src.api.routes import router
from src.config import Settings, get_settings
from src.services.case_service import CaseService, get_case_service
from tests.support.runtime_reset import reset_runtime_state

CASE_ID = "23600000-0000-4000-8000-000000000003"
ANALYST_ID = "23600000-0000-4000-8000-000000000002"
OTHER_ANALYST_ID = "23600000-0000-4000-8000-000000000004"
ORG_ID = "23600000-0000-4000-8000-000000000005"
JUDGMENTS = ("Nghi ngờ vi phạm", "Nghi oan-bất khả kháng", "Chưa đủ cơ sở")
BASE = f"/api/v1/cases/{CASE_ID}"


@pytest_asyncio.fixture
async def staged_client(monkeypatch):
    for key in ("DATABASE_URL", "REDIS_URL", "QDRANT_URL", "LANGSMITH_API_KEY"):
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("TEST_AUTH_ENABLED", "true")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    reset_runtime_state()
    service = CaseService(Settings(app_env="test", test_auth_enabled=True, database_url="", redis_url=""))
    # Storage transports only; never replace a case/judgment/adjudication result.
    monkeypatch.setattr(CaseService, "_get_db_connection", lambda self: None)
    monkeypatch.setattr(CaseService, "get_redis_client", lambda self: None)
    service._cases.clear()
    service._case_aliases.clear()
    service._active_leases.clear()
    service._adjudications.clear()
    service._principal_roles.update({ANALYST_ID: "analyst", OTHER_ANALYST_ID: "analyst"})
    now = datetime.now(UTC)
    service._cases[CASE_ID] = {
        "id": CASE_ID,
        "organization_id": ORG_ID,
        "assignment_id": "assignment-236",
        "evidence_snapshot_id": "snapshot-236",
        "suspected_category": "intentional_dic",
        "status": "ready",
        "priority_tier": 1,
        "priority_score": 80,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    service._assignments["assignment-236"] = {"id": "assignment-236", "trip_id": "trip-236"}
    service._trips["trip-236"] = {"id": "trip-236", "status": "cancelled"}
    service._evidence_snapshots["snapshot-236"] = {"id": "snapshot-236", "case_id": CASE_ID}
    service._feature_sets["feature-236"] = {
        "id": "feature-236",
        "evidence_snapshot_id": "snapshot-236",
        "stationary_duration_s": 240,
    }
    service._model_assessments["assessment-236"] = {
        "id": "assessment-236",
        "evidence_snapshot_id": "snapshot-236",
        "category": "intentional_dic",
        "confidence": 0.92,
        "recommended_action": "Agree",
    }
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_case_service] = lambda: service
    actor = {"id": ANALYST_ID, "role": "analyst", "org": ORG_ID}
    app.dependency_overrides[require_principal] = lambda: Principal(
        id=actor["id"], organization_id=actor["org"], roles=frozenset({actor["role"]})
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, actor
    reset_runtime_state()
    get_settings.cache_clear()


async def claim(client):
    response = await client.post(f"{BASE}/claim", json={"analyst_id": ANALYST_ID})
    assert response.status_code == 200, response.text


async def commit(client, judgment=JUDGMENTS[0], note=None):
    payload = {"analyst_id": ANALYST_ID, "judgment": judgment}
    if note is not None:
        payload["note"] = note
    response = await client.post(f"{BASE}/preliminary-assessment", json=payload)
    assert response.status_code in (200, 201), (
        f"Claimed analyst must be able to commit independent judgment: {response.status_code} {response.text}"
    )
    return response.json()


async def test_fixture_supplies_real_case_evidence_and_ai_assessment_through_http(staged_client):
    client, _ = staged_client
    response = await client.get(BASE)
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["assessment"]["category"] == "intentional_dic"
    assert detail["assessment"]["confidence"] == 0.92
    assert detail["features"]["stationary_duration_s"] == 240


@pytest.mark.parametrize("judgment", JUDGMENTS)
@pytest.mark.parametrize("note", [None, "Đối chiếu dữ kiện trước khi xem AI."])
async def test_claimed_analyst_commits_each_choice_and_reload_restores_it(staged_client, judgment, note):
    client, _ = staged_client
    await claim(client)
    record = await commit(client, judgment, note)
    response = await client.get(BASE)
    assert response.status_code == 200, response.text
    restored = response.json().get("preliminary_judgment")
    assert restored is not None
    assert restored["id"] == record["id"]
    assert restored["analyst_id"] == ANALYST_ID
    assert restored["judgment"] == judgment
    assert restored.get("note") == note


async def test_reload_before_commit_explicitly_keeps_gate_uncommitted(staged_client):
    client, _ = staged_client
    await claim(client)
    for _ in range(2):
        response = await client.get(BASE)
        assert response.status_code == 200, response.text
        assert "preliminary_judgment" in response.json(), "Reload cannot infer gate state from absent schema data"
        assert response.json()["preliminary_judgment"] is None


async def test_unclaimed_case_cannot_record_a_judgment(staged_client):
    client, _ = staged_client
    response = await client.post(
        f"{BASE}/preliminary-assessment", json={"analyst_id": ANALYST_ID, "judgment": JUDGMENTS[0]}
    )
    assert response.status_code == 409, response.text


async def test_other_analyst_cannot_record_the_claimants_judgment(staged_client):
    client, actor = staged_client
    await claim(client)
    actor["id"] = OTHER_ANALYST_ID
    response = await client.post(
        f"{BASE}/preliminary-assessment", json={"analyst_id": OTHER_ANALYST_ID, "judgment": JUDGMENTS[0]}
    )
    assert response.status_code == 409, response.text


async def test_judgment_rejects_spoofed_analyst_signature(staged_client):
    client, _ = staged_client
    await claim(client)
    response = await client.post(
        f"{BASE}/preliminary-assessment", json={"analyst_id": OTHER_ANALYST_ID, "judgment": JUDGMENTS[0]}
    )
    assert response.status_code == 403, response.text


async def test_judgment_rejects_a_fourth_choice(staged_client):
    client, _ = staged_client
    await claim(client)
    response = await client.post(
        f"{BASE}/preliminary-assessment", json={"analyst_id": ANALYST_ID, "judgment": "AI chose for me"}
    )
    assert response.status_code == 422, response.text


async def test_double_commit_cannot_overwrite_first_independent_judgment(staged_client):
    client, _ = staged_client
    await claim(client)
    first = await commit(client, JUDGMENTS[0], "Initial independent judgment")
    retry = await client.post(
        f"{BASE}/preliminary-assessment",
        json={"analyst_id": ANALYST_ID, "judgment": JUDGMENTS[0], "note": "Initial independent judgment"},
    )
    assert retry.status_code in (200, 409), retry.text
    if retry.status_code == 200:
        assert retry.json()["id"] == first["id"]
    replacement = await client.post(
        f"{BASE}/preliminary-assessment", json={"analyst_id": ANALYST_ID, "judgment": JUDGMENTS[1]}
    )
    assert replacement.status_code == 409, replacement.text
    restored = (await client.get(BASE)).json()["preliminary_judgment"]
    assert restored["id"] == first["id"]
    assert restored["judgment"] == JUDGMENTS[0]


@pytest.mark.parametrize(
    "judgment,outcome,delta", [(JUDGMENTS[0], "AGREE", "match"), (JUDGMENTS[1], "DISAGREE", "mismatch")]
)
async def test_final_decision_exposes_independent_judgment_ai_suggestion_and_delta_in_history_and_audit(
    staged_client, judgment, outcome, delta
):
    client, _ = staged_client
    await claim(client)
    record = await commit(client, judgment)
    before = (await client.get(BASE)).json()
    response = await client.post(
        f"{BASE}/adjudicate",
        json={
            "analyst_id": ANALYST_ID,
            "outcome": outcome,
            "rationale": "1234567890",
            "expected_case_version": before["case"]["version"],
            "preliminary_judgment_id": record["id"],
        },
    )
    assert response.status_code == 200, response.text
    # Read the retained history record through HTTP, never inspect private writes.
    history = await client.get("/api/v1/cases/history")
    assert history.status_code == 200, history.text
    assert CASE_ID in [item["id"] for item in history.json()["items"]]
    detail = (await client.get(BASE)).json()
    decision = detail.get("adjudication")
    assert decision is not None, "Final decision must remain readable in case history"
    assert decision["preliminary_judgment_id"] == record["id"]
    assert decision["preliminary_judgment"]["judgment"] == judgment
    assert decision["ai_suggestion"]["category"] == "intentional_dic"
    assert decision["ai_suggestion"]["confidence"] == 0.92
    assert decision["delta"] == delta
    audit = await client.get("/api/v1/analyst/audit")
    assert audit.status_code == 200, audit.text
    entry = next((row for row in audit.json()["ledger"] if row["case_id"] == CASE_ID), None)
    assert entry is not None, "Signed decision missing from analyst audit"
    assert entry["preliminary_judgment_id"] == record["id"]
    assert entry["delta"] == delta


@pytest.mark.parametrize("outcome", ["AGREE", "DISAGREE"])
async def test_revealed_mismatch_still_requires_ten_character_final_rationale(staged_client, outcome):
    client, _ = staged_client
    await claim(client)
    record = await commit(client, JUDGMENTS[1])
    detail = (await client.get(BASE)).json()
    response = await client.post(
        f"{BASE}/adjudicate",
        json={
            "analyst_id": ANALYST_ID,
            "outcome": outcome,
            "rationale": "123456789",
            "expected_case_version": detail["case"]["version"],
            "preliminary_judgment_id": record["id"],
        },
    )
    assert response.status_code == 422, response.text
    assert (await client.get(BASE)).json()["case"]["version"] == detail["case"]["version"]


@pytest.mark.parametrize("outcome", ["AGREE", "DISAGREE"])
async def test_direct_final_request_still_rejects_a_different_analyst_signature(staged_client, outcome):
    client, _ = staged_client
    await claim(client)
    detail = (await client.get(BASE)).json()
    response = await client.post(
        f"{BASE}/adjudicate",
        json={
            "analyst_id": OTHER_ANALYST_ID,
            "outcome": outcome,
            "rationale": "Signed by somebody else",
            "expected_case_version": detail["case"]["version"],
        },
    )
    assert response.status_code == 403, response.text


async def test_evidence_request_is_valid_before_preliminary_commit(staged_client):
    client, _ = staged_client
    await claim(client)
    response = await client.post(
        f"{BASE}/actions",
        json={
            "analyst_id": ANALYST_ID,
            "action_type": "REQUEST_EVIDENCE",
            "notes": "Need independent traffic corroboration",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["new_case_status"] == "evidence_requested"


@pytest.mark.parametrize("outcome", ["AGREE", "DISAGREE"])
async def test_final_decision_cannot_silently_discard_a_nonexistent_judgment_reference(staged_client, outcome):
    client, _ = staged_client
    await claim(client)
    before = (await client.get(BASE)).json()
    response = await client.post(
        f"{BASE}/adjudicate",
        json={
            "analyst_id": ANALYST_ID,
            "outcome": outcome,
            "rationale": "Independent finding must be linked, not fabricated",
            "expected_case_version": before["case"]["version"],
            "preliminary_judgment_id": "23600000-0000-4000-8000-000000000099",
        },
    )
    assert response.status_code == 409, "A nonexistent judgment must not yield a signed final decision"
    assert (await client.get(BASE)).json()["case"]["version"] == before["case"]["version"]
