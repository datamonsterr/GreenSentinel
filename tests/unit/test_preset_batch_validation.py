"""Unit tests for preset batch run parameter validation (Issue #458)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src.models.test_simulation import PresetBatchRunCreate
from src.services.test_preset_batch import validate_preset_batch_run_params


def test_preset_batch_run_create_schema_validation():
    """Pydantic model validation rejects invalid parameters."""
    d_id = uuid4()
    # Valid defaults
    valid = PresetBatchRunCreate(driver_ids=[d_id])
    assert valid.trip_limit is None
    assert valid.trips_per_batch == 1
    assert valid.interval_s == 1.0
    assert valid.driver_ids == [d_id]

    # missing driver_ids rejected
    with pytest.raises(ValidationError):
        PresetBatchRunCreate()

    # empty driver_ids rejected
    with pytest.raises(ValidationError):
        PresetBatchRunCreate(driver_ids=[])

    # trips_per_batch < 1 rejected
    with pytest.raises(ValidationError):
        PresetBatchRunCreate(driver_ids=[d_id], trips_per_batch=0)
    with pytest.raises(ValidationError):
        PresetBatchRunCreate(driver_ids=[d_id], trips_per_batch=-1)

    # interval_s <= 0 rejected
    with pytest.raises(ValidationError):
        PresetBatchRunCreate(driver_ids=[d_id], interval_s=0.0)
    with pytest.raises(ValidationError):
        PresetBatchRunCreate(driver_ids=[d_id], interval_s=-0.5)


def test_validate_preset_batch_run_params_boundary():
    """validate_preset_batch_run_params enforces 1..available trip_limit."""
    # Available trips = 100 for synthesized-vietnam sample
    available_trips = 100
    d_id = uuid4()

    # trip_limit == None is valid (means 100%)
    params = PresetBatchRunCreate(driver_ids=[d_id], trip_limit=None, trips_per_batch=5, interval_s=1.0)
    limit = validate_preset_batch_run_params(params, available_trips)
    assert limit == 100

    # trip_limit in [1, available_trips] is valid
    params_1 = PresetBatchRunCreate(driver_ids=[d_id], trip_limit=1, trips_per_batch=1, interval_s=1.0)
    assert validate_preset_batch_run_params(params_1, available_trips) == 1

    params_100 = PresetBatchRunCreate(driver_ids=[d_id], trip_limit=100, trips_per_batch=10, interval_s=2.0)
    assert validate_preset_batch_run_params(params_100, available_trips) == 100

    # trip_limit < 1 rejected with 422
    params_0 = PresetBatchRunCreate.model_construct(driver_ids=[d_id], trip_limit=0, trips_per_batch=1, interval_s=1.0)
    with pytest.raises(HTTPException) as exc_info:
        validate_preset_batch_run_params(params_0, available_trips)
    assert exc_info.value.status_code == 422
    assert "trip_limit" in exc_info.value.detail

    # trip_limit > available_trips rejected with 422
    params_101 = PresetBatchRunCreate(driver_ids=[d_id], trip_limit=101, trips_per_batch=1, interval_s=1.0)
    with pytest.raises(HTTPException) as exc_info:
        validate_preset_batch_run_params(params_101, available_trips)
    assert exc_info.value.status_code == 422
    assert "trip_limit" in exc_info.value.detail
