"""Structured motivation assessment (S-M): mapping, LLM fallback, API roles."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.auth import Principal, require_principal
from src.api.routes import get_case_service
from src.main import app
from src.models.schemas import DriverMotivationAssessment
from src.services import case_motivation_service as svc

GPS = [{"gps_state": "mock_reported", "mock_location_reported": True}, {"gps_state": "valid"}]


def _build(trip=None, features=None, telemetry=None):
    return svc.build_structured_assessment(trip or {}, features or {}, telemetry if telemetry is not None else GPS)


def test_no_data_is_unclear_low_confidence():
    d = svc.build_structured_assessment({}, {}, [])
    assert d.motive_category == "unclear" and d.confidence == 0.2 and d.amount_at_stake_vnd is None
    assert d.source == "rule" and d.rationale


def test_platform_incident_without_mock_is_platform_fault():
    d = _build(features={"fare_delta_vnd": 20000, "platform_incident_confirmed": True}, telemetry=[{"gps_state": "valid"}])
    assert d.motive_category == "platform_fault"
    assert d.amount_at_stake_vnd == 20000
    assert any(s.code == "platform_incident" for s in d.signals)


def test_surge_with_mock_is_subsidy_surge_amount_computed_in_code():
    d = _build(features={"fare_delta_vnd": 10000, "surge_capture_incremental_vnd": 5000})
    assert d.motive_category == "subsidy_surge"
    assert d.amount_at_stake_vnd == 15000.0
    assert {s.code for s in d.signals} >= {"mock_location", "fare_delta", "surge_capture"}
    assert 0.35 < d.confidence <= 0.85


def test_bonus_with_abnormality_is_reward_threshold():
    d = _build(trip={"bonus_amount_vnd": 50000})
    assert d.motive_category == "reward_threshold" and d.amount_at_stake_vnd == 50000


def test_amount_falls_back_to_trip_fare_and_bonus_when_no_delta():
    d = _build(trip={"fare_amount_vnd": 85000})
    assert d.amount_at_stake_vnd == 85000
    d = _build(trip={"fare_amount_vnd": 85000, "bonus_amount_vnd": 5000}, telemetry=[{"gps_state": "valid"}])
    assert d.amount_at_stake_vnd == 90000


def test_fare_delta_with_mock_is_fare_inflation():
    d = _build(features={"fare_delta_vnd": 30000})
    assert d.motive_category == "fare_inflation" and d.amount_at_stake_vnd == 30000


@pytest.mark.asyncio
async def test_llm_rationale_used_when_valid_and_fallback_on_failure():
    feats = {"fare_delta_vnd": 30000}
    ai_text = "Có thể tài xế đã cố tình tăng cước; cần đối chiếu thêm bằng chứng định vị trước khi kết luận."
    with patch.object(svc, "generate_motivation_assessment", AsyncMock(
        return_value=DriverMotivationAssessment(economic_incentive_reward=30000, natural_vietnamese_narrative=ai_text))):
        d = await svc.generate_assessment(trip={}, features=feats, telemetry=GPS)
    assert d.source == "ai" and d.rationale == ai_text and d.motive_category == "fare_inflation"
    with patch.object(svc, "generate_motivation_assessment", AsyncMock(side_effect=TimeoutError())):
        d = await svc.generate_assessment(trip={}, features=feats, telemetry=GPS)
    assert d.source == "rule" and d.rationale == svc._RATIONALE_VI["fare_inflation"]


def test_edit_schema_rejects_bad_category_and_confidence():
    with pytest.raises(ValueError):
        svc.MotivationEdit(motive_category="greed", confidence=0.5, rationale="x")
    with pytest.raises(ValueError):
        svc.MotivationEdit(motive_category="unclear", confidence=1.5, rationale="x")


# ---- API ------------------------------------------------------------------------------------------

SAVED = {"id": "a1", "case_id": "c1", "version": 2, "motive_category": "unclear", "status": "draft", "source": "analyst"}


@pytest.fixture
def client_for():
    case_service = MagicMock()
    case_service._resolve_case_id = lambda cid: cid
    case_service._get_case_detail_data = AsyncMock(
        return_value=SimpleNamespace(trip={}, features={"fare_delta_vnd": 30000}, telemetry_samples=GPS,
                                     case=SimpleNamespace(trip_id="t1", id="c1"))
    )

    def make(role):
        p = Principal(id="p1", organization_id="org1", roles=frozenset({role}))
        app.dependency_overrides[require_principal] = lambda: p
        app.dependency_overrides[get_case_service] = lambda: case_service
        return TestClient(app, raise_server_exceptions=False)

    yield make
    app.dependency_overrides.clear()


def test_get_returns_unsaved_rule_draft_when_nothing_persisted(client_for):
    c = client_for("analyst")
    with patch.object(svc, "load", return_value=(None, [])), patch("src.api.routes.require_case_scope"):
        r = c.get("/cases/c1/motivation")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["persisted"] is False and body["assessment"]["version"] == 0
    assert body["assessment"]["motive_category"] == "fare_inflation"


def test_get_returns_persisted_latest(client_for):
    c = client_for("reviewer")
    with patch.object(svc, "load", return_value=(SAVED, [{"version": 2}])), patch("src.api.routes.require_case_scope"):
        r = c.get("/cases/c1/motivation")
    assert r.status_code == 200 and r.json()["persisted"] is True and r.json()["assessment"]["version"] == 2


@pytest.mark.parametrize("role", ["reviewer", "ops_director", "marketplace_director"])
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/cases/c1/motivation/generate", None),
        ("PUT", "/cases/c1/motivation", {"motive_category": "unclear", "confidence": 0.5, "rationale": "x"}),
        ("POST", "/cases/c1/motivation/confirm", None),
    ],
)
def test_read_only_roles_cannot_write(client_for, role, method, path, body):
    r = client_for(role).request(method, path, json=body)
    assert r.status_code == 403 and "Insufficient role" in r.text


def test_analyst_generate_edit_confirm(client_for):
    c = client_for("analyst")
    with patch("src.api.routes.require_case_scope"), \
            patch.object(svc, "save_generated", return_value={**SAVED, "version": 1, "source": "rule"}) as gen, \
            patch.object(svc, "save_edit", return_value=SAVED) as edit, \
            patch.object(svc, "confirm", return_value={**SAVED, "status": "confirmed"}) as conf:
        with patch.object(svc, "generate_motivation_assessment", AsyncMock(side_effect=TimeoutError())):
            g = c.post("/cases/c1/motivation/generate")
        e = c.put("/cases/c1/motivation", json={"motive_category": "unclear", "confidence": 0.4, "rationale": "Chưa rõ",
                                                "expected_version": 1})
        k = c.post("/cases/c1/motivation/confirm", json={"expected_version": 2})
    assert g.status_code == e.status_code == k.status_code == 200
    assert gen.call_args.args[4].motive_category == "fare_inflation"
    assert edit.call_args.args[4].expected_version == 1
    assert conf.call_args.args[4] == 2 and k.json()["assessment"]["status"] == "confirmed"


def test_edit_rejects_unknown_category(client_for):
    r = client_for("analyst").put("/cases/c1/motivation", json={"motive_category": "greed", "confidence": 0.4, "rationale": "x"})
    assert r.status_code == 422
