"""B1: case chat must not 404 for the case owner.

Regression: routes called dispute_service.get_dispute_context(case_id)
WITHOUT driver_id, so after the fail-closed ownership change every owner
got 'Case ... not found'. These tests hit the real routes (no mocking of
get_dispute_context) with a driver principal owning the case and assert
200; a foreign driver gets 404.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.services.case_service import get_case_service

TEST_ORG = "018f2f4e-0000-7000-8000-000000000001"


@pytest.fixture(autouse=True)
def _force_memory_fallback():
    """DB-independent: save/restore the app-tables flag around each test."""
    cs = get_case_service()
    prev = cs._has_app_tables
    cs._has_app_tables = False
    try:
        yield
    finally:
        cs._has_app_tables = prev


def _setup_owned_case(case_id: str, driver_id: str) -> None:
    cs = get_case_service()
    cs._has_app_tables = False
    asgn_id = f"asgn-{case_id}"
    cs._drivers[driver_id] = {
        "id": driver_id,
        "display_name": f"Driver {driver_id}",
        "account_status": "active",
        "organization_id": TEST_ORG,
    }
    cs._assignments[asgn_id] = {
        "id": asgn_id,
        "driver_id": driver_id,
        "trip_id": f"trip-{case_id}",
    }
    cs._cases[case_id] = {
        "id": case_id,
        "assignment_id": asgn_id,
        "organization_id": TEST_ORG,
        "status": "ready",
        "dispute_status": "not_disputed",
        "suspected_category": "ERR-01",
    }


def _headers(driver_id: str | None) -> dict[str, str]:
    if driver_id is None:
        return {"X-Role": "driver"}
    return {"X-Driver-ID": driver_id, "X-Role": "driver"}


@pytest.mark.asyncio
async def test_owner_dispute_context_200(client: AsyncClient):
    case_id = f"case-own-ctx-{uuid4().hex[:6]}"
    owner = f"drv-owner-{uuid4().hex[:6]}"
    _setup_owned_case(case_id, owner)
    res = await client.get(f"/api/v1/driver/cases/{case_id}/dispute", headers=_headers(owner))
    assert res.status_code == 200, res.text
    assert res.json()["driver_id"] == owner


@pytest.mark.asyncio
async def test_owner_session_200_foreign_404(client: AsyncClient):
    case_id = str(uuid4())
    owner = f"drv-owner-{uuid4().hex[:6]}"
    foreign = f"drv-foreign-{uuid4().hex[:6]}"
    _setup_owned_case(case_id, owner)

    res = await client.get(f"/api/v1/driver/cases/{case_id}/session", headers=_headers(owner))
    assert res.status_code == 200, res.text

    res_foreign = await client.get(f"/api/v1/driver/cases/{case_id}/session", headers=_headers(foreign))
    assert res_foreign.status_code == 404, res_foreign.text


@pytest.mark.asyncio
async def test_owner_post_chat_200_foreign_404(client: AsyncClient):
    case_id = f"case-own-chat-{uuid4().hex[:6]}"
    owner = f"drv-owner-{uuid4().hex[:6]}"
    foreign = f"drv-foreign-{uuid4().hex[:6]}"
    _setup_owned_case(case_id, owner)

    payload = {"message": "Tôi xin giải trình về trường hợp này", "claim_type": "passenger_wait"}
    res = await client.post(f"/api/v1/driver/cases/{case_id}/chat", json=payload, headers=_headers(owner))
    assert res.status_code == 200, res.text
    assert res.json()["case_id"] == case_id

    res_foreign = await client.post(f"/api/v1/driver/cases/{case_id}/chat", json=payload, headers=_headers(foreign))
    assert res_foreign.status_code == 404, res_foreign.text


@pytest.mark.asyncio
async def test_owner_get_stream_200_foreign_404(client: AsyncClient):
    case_id = f"case-own-gs-{uuid4().hex[:6]}"
    owner = f"drv-owner-{uuid4().hex[:6]}"
    foreign = f"drv-foreign-{uuid4().hex[:6]}"
    _setup_owned_case(case_id, owner)

    res = await client.get(
        f"/api/v1/driver/cases/{case_id}/chat/stream",
        params={"message": "Tôi xin giải trình"},
        headers=_headers(owner),
    )
    assert res.status_code == 200, res.text
    assert "text/event-stream" in res.headers["content-type"]

    res_foreign = await client.get(
        f"/api/v1/driver/cases/{case_id}/chat/stream",
        params={"message": "Tôi xin giải trình"},
        headers=_headers(foreign),
    )
    assert res_foreign.status_code == 404, res_foreign.text


@pytest.mark.asyncio
async def test_owner_post_stream_200_foreign_404(client: AsyncClient):
    case_id = f"case-own-ps-{uuid4().hex[:6]}"
    owner = f"drv-owner-{uuid4().hex[:6]}"
    foreign = f"drv-foreign-{uuid4().hex[:6]}"
    _setup_owned_case(case_id, owner)

    payload = {"message": "Tôi xin giải trình về trường hợp này"}
    res = await client.post(f"/api/v1/driver/cases/{case_id}/chat/stream", json=payload, headers=_headers(owner))
    assert res.status_code == 200, res.text
    assert "text/event-stream" in res.headers["content-type"]

    res_foreign = await client.post(
        f"/api/v1/driver/cases/{case_id}/chat/stream", json=payload, headers=_headers(foreign)
    )
    assert res_foreign.status_code == 404, res_foreign.text


@pytest.mark.asyncio
async def test_driver_guest_path_still_works(client: AsyncClient):
    """Test-auth driver-guest (no X-Driver-ID) keeps reaching the case."""
    case_id = f"case-guest-{uuid4().hex[:6]}"
    owner = f"drv-owner-{uuid4().hex[:6]}"
    _setup_owned_case(case_id, owner)

    res = await client.get(f"/api/v1/driver/cases/{case_id}/dispute", headers=_headers(None))
    assert res.status_code == 200, res.text
