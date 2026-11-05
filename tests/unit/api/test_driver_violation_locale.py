"""B3: Vietnamese titles carry no English parenthetical; locale selects language."""

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


def _setup_case(case_id: str, driver_id: str, category: str = "ERR-03") -> None:
    cs = get_case_service()
    cs._has_app_tables = False
    asgn_id = f"asgn-{case_id}"
    cs._drivers[driver_id] = {
        "id": driver_id,
        "display_name": f"Driver {driver_id}",
        "account_status": "active",
        "organization_id": TEST_ORG,
    }
    cs._assignments[asgn_id] = {"id": asgn_id, "driver_id": driver_id, "trip_id": f"trip-{case_id}"}
    cs._cases[case_id] = {
        "id": case_id,
        "assignment_id": asgn_id,
        "organization_id": TEST_ORG,
        "status": "ready",
        "dispute_status": "not_disputed",
        "suspected_category": category,
    }


def test_vi_titles_have_no_english_parenthetical():
    from src.services.driver_dispute_service import VIOLATION_TITLE_MAP, violation_title

    assert set(VIOLATION_TITLE_MAP) == {"ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05"}
    for code in VIOLATION_TITLE_MAP:
        title = violation_title(code, "vi")
        assert "(" not in title and ")" not in title, f"{code}: {title}"


def test_en_titles_available():
    from src.services.driver_dispute_service import VIOLATION_TITLE_MAP_EN, violation_title

    for code in ("ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05"):
        title = violation_title(code, "en")
        assert title == VIOLATION_TITLE_MAP_EN[code]
        assert title


@pytest.mark.asyncio
async def test_dispute_context_defaults_to_vi(client: AsyncClient):
    case_id = f"case-loc-{uuid4().hex[:6]}"
    owner = f"drv-loc-{uuid4().hex[:6]}"
    _setup_case(case_id, owner, "ERR-03")
    res = await client.get(
        f"/api/v1/driver/cases/{case_id}/dispute", headers={"X-Driver-ID": owner, "X-Role": "driver"}
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["violation_code"] == "ERR-03"
    assert "(" not in data["violation_title"]


@pytest.mark.asyncio
async def test_dispute_context_locale_en_query(client: AsyncClient):
    case_id = f"case-loce-{uuid4().hex[:6]}"
    owner = f"drv-loce-{uuid4().hex[:6]}"
    _setup_case(case_id, owner, "ERR-03")
    res = await client.get(
        f"/api/v1/driver/cases/{case_id}/dispute?locale=en",
        headers={"X-Driver-ID": owner, "X-Role": "driver"},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["violation_code"] == "ERR-03"
    assert data["violation_title"] == "Incentive/policy exploitation via fake trips"


@pytest.mark.asyncio
async def test_dispute_context_locale_en_header(client: AsyncClient):
    case_id = f"case-loch-{uuid4().hex[:6]}"
    owner = f"drv-loch-{uuid4().hex[:6]}"
    _setup_case(case_id, owner, "ERR-02")
    res = await client.get(
        f"/api/v1/driver/cases/{case_id}/dispute",
        headers={"X-Driver-ID": owner, "X-Role": "driver", "Accept-Language": "en-US,en;q=0.9"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["violation_title"] == "Route deviation / stall-to-cancel"


@pytest.mark.asyncio
async def test_cases_list_locale_en_query(client: AsyncClient):
    case_id = f"case-list-{uuid4().hex[:6]}"
    owner = f"drv-list-{uuid4().hex[:6]}"
    _setup_case(case_id, owner, "ERR-05")
    res = await client.get("/api/v1/driver/cases?locale=en", headers={"X-Driver-ID": owner, "X-Role": "driver"})
    assert res.status_code == 200, res.text
    items = [i for i in res.json()["items"] if i["case_id"] == case_id]
    assert items, res.json()
    assert items[0]["violation_code"] == "ERR-05"
    assert items[0]["violation_title"] == "Fake GPS / technological manipulation"


@pytest.mark.asyncio
async def test_cases_list_defaults_to_vi(client: AsyncClient):
    case_id = f"case-listv-{uuid4().hex[:6]}"
    owner = f"drv-listv-{uuid4().hex[:6]}"
    _setup_case(case_id, owner, "ERR-05")
    res = await client.get("/api/v1/driver/cases", headers={"X-Driver-ID": owner, "X-Role": "driver"})
    assert res.status_code == 200, res.text
    items = [i for i in res.json()["items"] if i["case_id"] == case_id]
    assert items, res.json()
    assert items[0]["violation_title"] == "GPS giả hoặc thao túng công nghệ vị trí"
