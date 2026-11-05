"""Unit tests for classifier API routes (Slice W2)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from src.api.classifier_routes import (
    ClassifierUnavailableException,
    get_classifier_service,
)
from src.config import Settings, get_settings
from src.main import app


# Local ClassifierResult schema for tests (as instructed: defined locally in tests only)
class LocalClassifierResult(BaseModel):
    category: str = "no_violation"
    probabilities: dict[str, float] = {
        "no_violation": 0.95,
        "ERR-01": 0.01,
        "ERR-02": 0.01,
        "ERR-03": 0.01,
        "ERR-04": 0.01,
        "ERR-05": 0.01,
        "insufficient_evidence": 0.0,
    }
    confidence: float = 0.95
    guardrail_blocked: bool = False
    guardrail_reason: str | None = None
    model_version: str = "r3d_v2.1_20261019"
    artifact_sha: str = "d52e52ff"
    feature_ms: float = 12.5
    inference_ms: float = 25.0
    assessment_source: str = "r3d_classifier"


class FakeClassifier:
    """Fake classifier adhering to FraudClassifierProtocol for testing."""

    def __init__(self, should_fail: bool = False, model_version: str = "r3d_v2.1_20261019") -> None:
        self.should_fail = should_fail
        self.model_version = model_version
        self.artifact_shas = {
            "r3c": "1111aaaa",
            "r3f": "2222bbbb",
            "stacker": "3333cccc",
        }
        self.loaded_at = "2026-10-19T10:00:00Z"
        self.load_ms = 1500.0
        self.metrics = {"macro_f1": 0.868, "accuracy": 0.9507}

    def predict(self, bundle: dict[str, Any]) -> LocalClassifierResult:
        if self.should_fail:
            raise RuntimeError("Inference execution failure")
        trip_id = bundle.get("trip_id")
        cat = "ERR-02" if trip_id == "stall_trip" else "no_violation"
        return LocalClassifierResult(
            category=cat,
            model_version=self.model_version,
            feature_ms=10.0,
            inference_ms=20.0,
        )

    def predict_many(self, bundles: list[dict[str, Any]]) -> list[LocalClassifierResult]:
        if self.should_fail:
            raise RuntimeError("Batch inference execution failure")
        return [self.predict(b) for b in bundles]

    def get_info(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "artifact_shas": self.artifact_shas,
            "loaded_at": self.loaded_at,
            "load_ms": self.load_ms,
            "metrics": self.metrics,
        }


def _get_test_settings(allow_heuristic: bool = False, batch_max: int = 64) -> Settings:
    return Settings(
        app_env="test",
        test_auth_enabled=True,
        fraud_classifier_enabled=True,
        classifier_batch_max=batch_max,
        jev_allow_heuristic_fallback=allow_heuristic,
    )


@pytest.fixture
def fake_classifier():
    return FakeClassifier()


@pytest.fixture
def client(fake_classifier):
    app.dependency_overrides[get_classifier_service] = lambda: fake_classifier
    app.dependency_overrides[get_settings] = _get_test_settings
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestClassifierAuth:
    """Auth tests: reuse existing role guard (analyst, senior_analyst, demo_operator, admin)."""

    def test_assess_requires_auth_when_test_auth_disabled(self, fake_classifier):
        prod_settings = Settings(
            app_env="production",
            test_auth_enabled=False,
            clerk_secret_key="mock",
        )
        app.dependency_overrides[get_classifier_service] = lambda: fake_classifier
        app.dependency_overrides[get_settings] = lambda: prod_settings

        with TestClient(app) as test_client:
            resp = test_client.post("/api/v1/classifier/assess", json={"bundle": {"trip_id": "t1"}})
            assert resp.status_code == 401
        app.dependency_overrides.clear()

    def test_assess_forbidden_for_driver_role(self, fake_classifier):
        app.dependency_overrides[get_classifier_service] = lambda: fake_classifier
        app.dependency_overrides[get_settings] = _get_test_settings

        with TestClient(app) as test_client:
            headers = {"x-role": "driver", "x-principal-id": "driver-1"}
            resp = test_client.post(
                "/api/v1/classifier/assess",
                json={"bundle": {"trip_id": "t1"}},
                headers=headers,
            )
            assert resp.status_code == 403
        app.dependency_overrides.clear()

    @pytest.mark.parametrize("role", ["analyst", "senior_analyst", "demo_operator", "admin", "fraud_analyst"])
    def test_assess_allowed_for_analyst_roles(self, fake_classifier, role):
        app.dependency_overrides[get_classifier_service] = lambda: fake_classifier
        app.dependency_overrides[get_settings] = _get_test_settings

        with TestClient(app) as test_client:
            headers = {"x-role": role, "x-principal-id": f"{role}-1"}
            resp = test_client.post(
                "/api/v1/classifier/assess",
                json={"bundle": {"trip_id": "t1"}},
                headers=headers,
            )
            assert resp.status_code == 200
        app.dependency_overrides.clear()


class TestClassifierAssessEndpoints:
    """Test assess single and batch endpoints, headers, and payloads."""

    def test_assess_with_bundle_payload(self, client):
        headers = {"x-role": "analyst"}
        resp = client.post(
            "/api/v1/classifier/assess",
            json={"bundle": {"trip_id": "stall_trip"}},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["category"] == "ERR-02"
        assert data["model_version"] == "r3d_v2.1_20261019"
        assert "server-timing" in resp.headers
        st = resp.headers["server-timing"]
        assert "feat;dur=" in st
        assert "infer;dur=" in st
        assert "total;dur=" in st

    def test_assess_with_telemetry_event_payload(self, client):
        headers = {"x-role": "analyst"}
        resp = client.post(
            "/api/v1/classifier/assess",
            json={"telemetry_event": {"trip_id": "normal_trip"}},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["category"] == "no_violation"

    def test_assess_with_raw_trip_payload(self, client):
        headers = {"x-role": "analyst"}
        resp = client.post(
            "/api/v1/classifier/assess",
            json={"trip_id": "normal_trip", "points": []},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["category"] == "no_violation"

    def test_assess_with_advisory_enabled(self, client):
        headers = {"x-role": "analyst"}
        with patch("src.services.classifier_advisory.run_classifier_advisory") as mock_adv:
            from src.models.classifier_api import ClassifierAdvisoryResult

            mock_adv.return_value = ClassifierAdvisoryResult(
                llm_category="ERR-02",
                llm_probabilities={"ERR-02": 0.9},
                llm_model_used="inception/mercury-decide:free",
                llm_latency_ms=450.0,
                advisory_status="ok",
                agreement=True,
            )
            resp = client.post(
                "/api/v1/classifier/assess?advisory=true",
                json={"bundle": {"trip_id": "stall_trip"}},
                headers=headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["category"] == "ERR-02"
            assert data["advisory"] is not None
            assert data["advisory"]["llm_category"] == "ERR-02"
            assert data["advisory"]["agreement"] is True
            assert "advisory;dur=" in resp.headers["server-timing"]

    def test_assess_batch_success(self, client):
        headers = {"x-role": "analyst"}
        bundles = [{"trip_id": "stall_trip"}, {"trip_id": "normal_trip"}]
        resp = client.post(
            "/api/v1/classifier/assess/batch",
            json=bundles,
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["category"] == "ERR-02"
        assert data[1]["category"] == "no_violation"
        assert "server-timing" in resp.headers

    def test_assess_batch_limit_exceeded(self, client):
        headers = {"x-role": "analyst"}
        # Limit is 64 by default
        items = [{"trip_id": f"t_{i}"} for i in range(65)]
        resp = client.post(
            "/api/v1/classifier/assess/batch",
            json=items,
            headers=headers,
        )
        assert resp.status_code == 400
        assert "Batch size exceeds" in resp.json()["detail"]


class TestClassifierUnavailableAndHeuristic:
    """Test 503 path and heuristic-disabled semantics (#550)."""

    def test_503_when_classifier_unavailable_and_heuristic_disabled(self):
        def _unavailable_provider():
            raise ClassifierUnavailableException("Models missing on disk")

        app.dependency_overrides[get_classifier_service] = _unavailable_provider
        app.dependency_overrides[get_settings] = lambda: _get_test_settings(allow_heuristic=False)

        with TestClient(app) as test_client:
            headers = {"x-role": "analyst"}
            resp = test_client.post(
                "/api/v1/classifier/assess",
                json={"bundle": {"trip_id": "t1"}},
                headers=headers,
            )
            assert resp.status_code == 503
            body = resp.json()
            assert body["assessment_source"] == "classifier_unavailable"
            assert "Classifier unavailable" in body["detail"]
        app.dependency_overrides.clear()

    def test_heuristic_fallback_when_allowed(self):
        def _unavailable_provider():
            raise ClassifierUnavailableException("Models missing on disk")

        app.dependency_overrides[get_classifier_service] = _unavailable_provider
        app.dependency_overrides[get_settings] = lambda: _get_test_settings(allow_heuristic=True)

        with patch("src.services.jev_assessment_service.JevAssessmentService._calibrated_heuristic") as mock_heur:
            from src.services.jev_assessment_service import JevAssessmentResult

            mock_heur.return_value = JevAssessmentResult(
                category="no_violation",
                confidence=0.88,
                priority="P2",
                priority_tier=2,
                priority_score=10,
                model_used="jev_calibrated_heuristic",
                assessment_source="heuristic_fallback",
            )
            with TestClient(app) as test_client:
                headers = {"x-role": "analyst"}
                resp = test_client.post(
                    "/api/v1/classifier/assess",
                    json={"bundle": {"trip_id": "t1"}},
                    headers=headers,
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["assessment_source"] == "heuristic_fallback"
        app.dependency_overrides.clear()


class TestClassifierInfo:
    """Test GET /api/v1/classifier/info."""

    def test_get_info_success(self, client):
        headers = {"x-role": "analyst"}
        resp = client.get("/api/v1/classifier/info", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["model_version"] == "r3d_v2.1_20261019"
        assert data["artifact_shas"]["r3c"] == "1111aaaa"
        assert data["load_ms"] == 1500.0
        assert data["metrics"]["macro_f1"] == 0.868

    def test_get_info_503_when_unavailable(self):
        def _unavailable_provider():
            raise ClassifierUnavailableException("Model not loaded")

        app.dependency_overrides[get_classifier_service] = _unavailable_provider
        app.dependency_overrides[get_settings] = _get_test_settings

        with TestClient(app) as test_client:
            headers = {"x-role": "analyst"}
            resp = test_client.get("/api/v1/classifier/info", headers=headers)
            assert resp.status_code == 503
        app.dependency_overrides.clear()
