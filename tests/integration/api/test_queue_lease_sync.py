"""Queue lease synchronization and multi-analyst concurrency regression suite.

Covers Issue #144:
- Excludes actively leased cases from other analysts' available queue
- Includes claimed cases in claiming analyst's "mine" queue
- Rejects concurrent stale claims with 409 Conflict
- Rejects concurrent stale adjudication with 409 Conflict
- Restores available queue visibility immediately upon release
- Restores available queue visibility upon 300s lease expiration
- Blocks foreign analysts from releasing another analyst's lock
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.auth import Principal, require_principal
from src.api.routes import router
from src.config import Settings
from src.services.case_service import CaseService, get_case_service


@pytest.fixture
def lease_sync_app(monkeypatch):
    service = CaseService(Settings(app_env="test", database_url=""))
    monkeypatch.setattr(service, "_get_db_connection", lambda: None)
    monkeypatch.setattr(service, "get_redis_client", lambda: None)
    monkeypatch.setattr(service, "get_principal_role", lambda *args: "analyst")

    service._cases.clear()
    service._case_aliases.clear()
    service._active_leases.clear()

    # Seed 3 test cases
    for cid in ("case-101", "case-102", "case-103"):
        service._cases[cid] = {
            "id": cid,
            "status": "ready",
            "organization_id": "org-p063",
            "priority_tier": 1,
            "priority_score": 90,
            "version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_case_service] = lambda: service
    return app, service


@pytest.mark.asyncio
async def test_concurrent_analysts_available_queue_filters_foreign_leases(lease_sync_app):
    app, service = lease_sync_app

    # Analyst A claims case-101
    service._active_leases["case-101"] = {
        "analyst_id": "analyst-a",
        "role": "analyst",
        "expires_at": datetime.now(UTC) + timedelta(seconds=300),
    }

    # Authenticated client for Analyst B
    async def get_analyst_b():
        return Principal(
            id="analyst-b",
            organization_id="org-p063",
            roles=frozenset(["analyst"]),
        )

    app.dependency_overrides[require_principal] = get_analyst_b

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Analyst B asks for available cases
        resp_b_avail = await client.get("/api/v1/cases?availability=available")
        assert resp_b_avail.status_code == 200
        b_avail_items = resp_b_avail.json()["items"]
        b_avail_ids = [item["id"] for item in b_avail_items]
        # case-101 MUST be excluded from B's available queue
        assert "case-101" not in b_avail_ids
        assert "case-102" in b_avail_ids
        assert "case-103" in b_avail_ids

        # 2. Analyst B asks for My Cases
        resp_b_mine = await client.get("/api/v1/cases?availability=mine")
        assert resp_b_mine.status_code == 200
        b_mine_ids = [item["id"] for item in resp_b_mine.json()["items"]]
        assert "case-101" not in b_mine_ids

    # Authenticated client for Analyst A
    async def get_analyst_a():
        return Principal(
            id="analyst-a",
            organization_id="org-p063",
            roles=frozenset(["analyst"]),
        )

    app.dependency_overrides[require_principal] = get_analyst_a

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 3. Analyst A asks for My Cases
        resp_a_mine = await client.get("/api/v1/cases?availability=mine")
        assert resp_a_mine.status_code == 200
        a_mine_ids = [item["id"] for item in resp_a_mine.json()["items"]]
        # case-101 MUST be in Analyst A's My Cases
        assert "case-101" in a_mine_ids


@pytest.mark.asyncio
async def test_stale_claim_conflict_returns_409(lease_sync_app):
    app, service = lease_sync_app

    # Analyst A claims case-101
    service._active_leases["case-101"] = {
        "analyst_id": "analyst-a",
        "role": "analyst",
        "expires_at": datetime.now(UTC) + timedelta(seconds=300),
    }

    # Analyst B attempts to claim case-101
    async def get_analyst_b():
        return Principal(id="analyst-b", organization_id="org-p063", roles=frozenset(["analyst"]))

    app.dependency_overrides[require_principal] = get_analyst_b

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        claim_resp = await client.post(
            "/api/v1/cases/case-101/claim",
            json={"analyst_id": "analyst-b", "lease_duration_seconds": 300},
        )
        assert claim_resp.status_code == 409
        err = claim_resp.json()
        assert "currently claimed by analyst analyst-a" in err["detail"]


@pytest.mark.asyncio
async def test_stale_adjudication_conflict_returns_409(lease_sync_app):
    app, service = lease_sync_app

    # Analyst A holds active lease on case-101
    service._active_leases["case-101"] = {
        "analyst_id": "analyst-a",
        "role": "analyst",
        "expires_at": datetime.now(UTC) + timedelta(seconds=300),
    }

    # Analyst B attempts to adjudicate case-101
    async def get_analyst_b():
        return Principal(id="analyst-b", organization_id="org-p063", roles=frozenset(["analyst"]))

    app.dependency_overrides[require_principal] = get_analyst_b

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        adj_resp = await client.post(
            "/api/v1/cases/case-101/adjudicate",
            json={
                "outcome": "AGREE",
                "analyst_id": "analyst-b",
                "rationale": "Attempting decision from stale session",
                "expected_case_version": 1,
            },
        )
        assert adj_resp.status_code == 409
        assert "currently claimed by analyst analyst-a" in adj_resp.json()["detail"]


@pytest.mark.asyncio
async def test_lease_release_and_expiration_restores_available_queue(lease_sync_app):
    app, service = lease_sync_app

    # 1. Analyst A claims case-101
    service._active_leases["case-101"] = {
        "analyst_id": "analyst-a",
        "role": "analyst",
        "expires_at": datetime.now(UTC) + timedelta(seconds=300),
    }

    # Analyst B checks: case-101 excluded
    async def get_analyst_b():
        return Principal(id="analyst-b", organization_id="org-p063", roles=frozenset(["analyst"]))

    app.dependency_overrides[require_principal] = get_analyst_b

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/cases?availability=available")
        assert "case-101" not in [c["id"] for c in resp.json()["items"]]

    # 2. Analyst A releases the lease
    async def get_analyst_a():
        return Principal(id="analyst-a", organization_id="org-p063", roles=frozenset(["analyst"]))

    app.dependency_overrides[require_principal] = get_analyst_a

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        rel_resp = await client.post("/api/v1/cases/case-101/release", json={"analyst_id": "analyst-a"})
        assert rel_resp.status_code == 200

    # 3. Analyst B checks again: case-101 is restored to available!
    app.dependency_overrides[require_principal] = get_analyst_b
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp2 = await client.get("/api/v1/cases?availability=available")
        assert "case-101" in [c["id"] for c in resp2.json()["items"]]

        # Analyst B can now claim it
        claim_resp = await client.post(
            "/api/v1/cases/case-101/claim",
            json={"analyst_id": "analyst-b", "lease_duration_seconds": 300},
        )
        assert claim_resp.status_code == 200
        assert claim_resp.json()["status"] == "claimed"

    # 4. Simulate lease expiry: set expires_at into the past
    service._active_leases["case-101"]["expires_at"] = datetime.now(UTC) - timedelta(seconds=1)

    # Analyst A checks available: expired lease means case-101 is available again
    app.dependency_overrides[require_principal] = get_analyst_a
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp3 = await client.get("/api/v1/cases?availability=available")
        assert "case-101" in [c["id"] for c in resp3.json()["items"]]


@pytest.mark.asyncio
async def test_foreign_analyst_cannot_release_lease(lease_sync_app):
    app, service = lease_sync_app

    # Analyst A holds lock
    service._active_leases["case-101"] = {
        "analyst_id": "analyst-a",
        "role": "analyst",
        "expires_at": datetime.now(UTC) + timedelta(seconds=300),
    }

    # Analyst B attempts release
    async def get_analyst_b():
        return Principal(id="analyst-b", organization_id="org-p063", roles=frozenset(["analyst"]))

    app.dependency_overrides[require_principal] = get_analyst_b

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        rel_resp = await client.post("/api/v1/cases/case-101/release", json={"analyst_id": "analyst-b"})
        assert rel_resp.status_code == 403
        assert "Permission denied" in rel_resp.json()["detail"]
