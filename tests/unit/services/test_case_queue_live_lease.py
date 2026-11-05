"""Unit tests for live review lease fields in case queue list APIs."""

from datetime import UTC, datetime, timedelta

import pytest

from src.config import Settings
from src.models.schemas import FraudCaseSummary
from src.services.case_service import CaseService


def test_fraud_case_summary_live_lease_defaults_and_fields():
    summary = FraudCaseSummary(
        id="case-1",
        status="ready",
        priority="P1",
        priority_score=90,
    )
    assert summary.active_lease_analyst_id is None
    assert summary.active_lease_expires_at is None

    exp = datetime.now(UTC) + timedelta(minutes=5)
    summary_with_lease = FraudCaseSummary(
        id="case-2",
        status="in_review",
        priority="P1",
        priority_score=90,
        active_lease_analyst_id="analyst-live",
        active_lease_expires_at=exp,
    )
    assert summary_with_lease.active_lease_analyst_id == "analyst-live"
    assert summary_with_lease.active_lease_expires_at == exp


@pytest.mark.asyncio
async def test_list_cases_in_memory_live_lease_unexpired_and_expired():
    service = CaseService(Settings(app_env="test", database_url=""))
    service._cases.clear()
    service._case_aliases.clear()
    service._active_leases.clear()

    now = datetime.now(UTC)
    unexpired_due = now + timedelta(minutes=5)
    expired_due = now - timedelta(minutes=5)

    # Case 1: unexpired active lease
    service._cases["case-active"] = {
        "id": "case-active",
        "status": "ready",
        "organization_id": "org-test",
        "priority_tier": 1,
        "priority_score": 90,
        "assigned_analyst_id": "analyst-orig",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    service._active_leases["case-active"] = {
        "analyst_id": "analyst-active",
        "expires_at": unexpired_due,
    }

    # Case 2: expired lease with assigned_analyst_id set
    service._cases["case-expired"] = {
        "id": "case-expired",
        "status": "ready",
        "organization_id": "org-test",
        "priority_tier": 1,
        "priority_score": 80,
        "assigned_analyst_id": "analyst-assigned",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    service._active_leases["case-expired"] = {
        "analyst_id": "analyst-expired",
        "expires_at": expired_due,
    }

    resp = await service.list_cases(organization_id="org-test", availability="all")
    items_by_id = {item.id: item for item in resp.items}

    # Unexpired lease -> live lease fields set
    active_item = items_by_id["case-active"]
    assert active_item.active_lease_analyst_id == "analyst-active"
    assert active_item.active_lease_expires_at == unexpired_due

    # Expired lease with assigned_analyst_id set -> live lease fields None, assigned_analyst_id unchanged
    expired_item = items_by_id["case-expired"]
    assert expired_item.active_lease_analyst_id is None
    assert expired_item.active_lease_expires_at is None
    assert expired_item.assigned_analyst_id == "analyst-assigned"


@pytest.mark.asyncio
async def test_list_case_history_in_memory_live_lease_unexpired_and_expired():
    service = CaseService(Settings(app_env="test", database_url=""))
    service._cases.clear()
    service._case_aliases.clear()
    service._active_leases.clear()

    now = datetime.now(UTC)
    unexpired_due = now + timedelta(minutes=5)
    expired_due = now - timedelta(minutes=5)

    # Case 1: unexpired active lease
    service._cases["case-hist-active"] = {
        "id": "case-hist-active",
        "status": "resolved",
        "organization_id": "org-test",
        "priority_tier": 1,
        "priority_score": 90,
        "assigned_analyst_id": "analyst-hist-orig",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    service._active_leases["case-hist-active"] = {
        "analyst_id": "analyst-hist-active",
        "expires_at": unexpired_due,
    }

    # Case 2: expired lease with assigned_analyst_id set
    service._cases["case-hist-expired"] = {
        "id": "case-hist-expired",
        "status": "resolved",
        "organization_id": "org-test",
        "priority_tier": 1,
        "priority_score": 80,
        "assigned_analyst_id": "analyst-hist-assigned",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    service._active_leases["case-hist-expired"] = {
        "analyst_id": "analyst-hist-expired",
        "expires_at": expired_due,
    }

    resp = await service.list_case_history(organization_id="org-test")
    items_by_id = {item.id: item for item in resp.items}

    # Unexpired lease -> live lease fields set
    active_item = items_by_id["case-hist-active"]
    assert active_item.active_lease_analyst_id == "analyst-hist-active"
    assert active_item.active_lease_expires_at == unexpired_due

    # Expired lease with assigned_analyst_id set -> live lease fields None, assigned_analyst_id unchanged
    expired_item = items_by_id["case-hist-expired"]
    assert expired_item.active_lease_analyst_id is None
    assert expired_item.active_lease_expires_at is None
    assert expired_item.assigned_analyst_id == "analyst-hist-assigned"


@pytest.mark.asyncio
async def test_list_cases_and_history_sql_join_and_column_mapping():
    service = CaseService(Settings(app_env="test", database_url="postgres://mock"))
    now = datetime.now(UTC)
    unexpired_due = now + timedelta(minutes=5)

    captured_queries = []

    class MockCursor:
        def __init__(self):
            self.query = ""

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, query, params=None):
            self.query = query
            captured_queries.append(query)

        def fetchone(self):
            return {"count": 1}

        def fetchall(self):
            return [
                {
                    "id": "case-sql-1",
                    "status": "ready",
                    "dispute_status": "not_disputed",
                    "dispute_deadline": None,
                    "priority_tier": 1,
                    "priority_score": 95,
                    "suspected_category": "fake_gps",
                    "assigned_analyst_id": "analyst-assigned",
                    "version": 1,
                    "created_at": now,
                    "updated_at": now,
                    "sla_due_at": None,
                    "trip_id": None,
                    "driver_id": None,
                    "assignment_id": None,
                    "driver_ref": None,
                    "driver_name": None,
                    "vehicle_plate": None,
                    "stationary_duration_s": None,
                    "analyst_name": None,
                    "trip_district": None,
                    "confidence": 0.88,
                    "active_lease_analyst_id": "analyst-sql-live",
                    "active_lease_expires_at": unexpired_due,
                    "staged_context": None,
                }
            ]

    class MockConn:
        def cursor(self):
            return MockCursor()

        def close(self):
            pass

    service._get_db_connection = lambda: MockConn()

    # Test list_cases SQL
    res_queue = await service.list_cases(organization_id="org-test")
    assert len(res_queue.items) == 1
    assert res_queue.items[0].active_lease_analyst_id == "analyst-sql-live"
    assert res_queue.items[0].active_lease_expires_at == unexpired_due
    assert res_queue.items[0].assigned_analyst_id == "analyst-assigned"

    # Test list_case_history SQL
    res_hist = await service.list_case_history(organization_id="org-test")
    assert len(res_hist.items) == 1
    assert res_hist.items[0].active_lease_analyst_id == "analyst-sql-live"
    assert res_hist.items[0].active_lease_expires_at == unexpired_due
    assert res_hist.items[0].assigned_analyst_id == "analyst-assigned"

    # Verify SQL lateral joins
    expected_join = (
        "LEFT JOIN LATERAL (SELECT analyst_id, expires_at FROM app.review_leases "
        "WHERE case_id = c.id AND expires_at > now() ORDER BY expires_at DESC LIMIT 1) lease ON true"
    )
    main_queries = [q for q in captured_queries if "SELECT c.id," in q]
    assert len(main_queries) == 2
    for q in main_queries:
        assert expected_join in q
