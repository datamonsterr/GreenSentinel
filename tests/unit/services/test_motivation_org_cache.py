"""S4-TENANT #294 P1d: motivation narrative cache is tenant-scoped."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.services import motivation_assessment_service as service

VI = "Hành trình có tín hiệu vị trí bị can thiệp. Khoản chênh lệch có thể tạo động cơ kinh tế, nhưng chuyên viên cần đối chiếu nguyên nhân trước khi kết luận về ý định của tài xế."
ORG_A = "11111111-1111-4111-8111-111111111111"
ORG_B = "22222222-2222-4222-8222-222222222222"


@pytest.fixture()
def isolated_provider(monkeypatch):
    service.clear_motivation_cache()
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content=VI)))
    monkeypatch.setattr(service, "get_llm", lambda: model, raising=False)
    yield model
    service.clear_motivation_cache()


@pytest.mark.asyncio
async def test_same_evidence_different_org_regenerates(isolated_provider):
    kwargs = dict(trip={"fare_delta_vnd": 10000}, telemetry=[{"gps_state": "mock_reported"}])
    first = await service.generate_motivation_assessment(**kwargs, organization_id=ORG_A)
    second = await service.generate_motivation_assessment(**kwargs, organization_id=ORG_B)
    assert first == second
    # One tenant must never reuse the other's cached narrative.
    assert isolated_provider.ainvoke.await_count == 2


@pytest.mark.asyncio
async def test_same_org_reuses_cache(isolated_provider):
    kwargs = dict(
        trip={"fare_delta_vnd": 10000},
        telemetry=[{"gps_state": "mock_reported"}],
        organization_id=ORG_A,
    )
    first = await service.generate_motivation_assessment(**kwargs)
    second = await service.generate_motivation_assessment(**kwargs)
    assert first == second
    assert isolated_provider.ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_unscoped_and_scoped_keys_do_not_collide(isolated_provider):
    kwargs = dict(trip={"fare_delta_vnd": 10000}, telemetry=[{"gps_state": "mock_reported"}])
    await service.generate_motivation_assessment(**kwargs)
    await service.generate_motivation_assessment(**kwargs, organization_id=ORG_A)
    assert isolated_provider.ainvoke.await_count == 2
