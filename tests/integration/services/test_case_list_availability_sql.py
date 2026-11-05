"""Regression: every queue availability filter must execute against the real schema."""

import pytest

from src.services.case_service import get_case_service

pytestmark = pytest.mark.docker


@pytest.mark.asyncio
@pytest.mark.parametrize("availability", ["available", "mine", "all"])
async def test_list_cases_availability_sql_executes(availability):
    service = get_case_service()
    conn = service._get_db_connection()
    assert conn is not None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id::text AS id FROM app.organizations LIMIT 1")
            org_id = cur.fetchone()["id"]
    finally:
        conn.close()

    page = await service.list_cases(
        availability=availability,
        analyst_id="018f2f4e-1000-7000-8000-000000000001",
        organization_id=org_id,
        limit=5,
    )
    assert page.total >= 0
