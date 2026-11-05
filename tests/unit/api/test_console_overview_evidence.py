"""Telemetry existence is not proof that a model processed a trip."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from src.api import test_routes
from src.api.auth import Principal


@pytest.mark.asyncio
@pytest.mark.parametrize("has_samples", [False, True])
async def test_overview_does_not_claim_unobserved_input_or_model_results(monkeypatch, has_samples):
    repository = Mock()
    repository.get_run.return_value = SimpleNamespace(status="QUEUED")
    repository.get_samples.return_value = [object()] if has_samples else []
    repository.list_cases.return_value = []
    repository.get_publish_submission.return_value = None
    monkeypatch.setattr(test_routes, "get_simulation_runner", lambda: SimpleNamespace(repository=repository))
    result = await test_routes.get_run_overview(uuid4(), "true", Principal("member", "org-a", frozenset()))
    assert result.trips_input == int(has_samples)
    assert result.trips_processed == 0
    assert result.trips_classified == 0
    assert result.classification_counts == {}
    assert result.stages[0].state != "done" or has_samples


@pytest.mark.asyncio
async def test_normal_persisted_classification_counts_without_fabricating_a_fraud_case(monkeypatch):
    repository = Mock()
    repository.get_run.return_value = SimpleNamespace(status="COMPLETED")
    repository.get_samples.return_value = [object()]
    repository.list_cases.return_value = []
    repository.get_publish_submission.return_value = {
        "response": {"status": "published"},
        "result": {"status": "processed", "category": "no_violation"},
    }
    monkeypatch.setattr(test_routes, "get_simulation_runner", lambda: SimpleNamespace(repository=repository))
    result = await test_routes.get_run_overview(uuid4(), "true", Principal("member", "org-a", frozenset()))
    assert result.trips_processed == 1
    assert result.trips_classified == 1
    assert result.classification_counts == {"no_violation": 1}
