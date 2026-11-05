"""Unit tests for driver directory, validation, and round-robin assignment (Issue #464)."""

from __future__ import annotations

from uuid import uuid4

from src.services.driver_directory import (
    DriverRecord,
    InMemoryDriverDirectory,
    assign_drivers_round_robin,
)


def test_round_robin_assignment_7_trips_3_drivers():
    """DoD: round-robin assignment (7 trips / 3 drivers gives 3/2/2 in order)."""
    d1 = uuid4()
    d2 = uuid4()
    d3 = uuid4()
    drivers = [d1, d2, d3]
    trips = [f"trip_{i}" for i in range(7)]

    assignments = assign_drivers_round_robin(trips, drivers)
    assert len(assignments) == 7

    # Check order: trip 0->d1, 1->d2, 2->d3, 3->d1, 4->d2, 5->d3, 6->d1
    expected_order = [d1, d2, d3, d1, d2, d3, d1]
    actual_drivers = [assigned_driver for _, assigned_driver in assignments]
    assert actual_drivers == expected_order

    # Check counts: d1 has 3, d2 has 2, d3 has 2
    counts = {d: actual_drivers.count(d) for d in drivers}
    assert counts[d1] == 3
    assert counts[d2] == 2
    assert counts[d3] == 2
    assert max(counts.values()) - min(counts.values()) <= 1


def test_driver_directory_validation():
    """Driver directory validates active Clerk-linked status and tenancy."""
    dir_svc = InMemoryDriverDirectory()
    org_a = "018f2f4e-0000-7000-8000-000000000001"
    org_b = "018f2f4e-0000-7000-8000-00000000000b"

    valid_driver_id = uuid4()
    principal_id = uuid4()
    vehicle_id = uuid4()

    dir_svc.register_driver(
        DriverRecord(
            driver_id=valid_driver_id,
            organization_id=org_a,
            principal_id=principal_id,
            external_subject="user_clerk_123",
            display_name="Nguyen Van A",
            email="driver.a@example.com",
            account_status="active",
            vehicle_id=vehicle_id,
            license_plate="29A-123.45",
        )
    )

    # 1. Valid active Clerk-linked driver found
    rec = dir_svc.get_active_driver(org_a, valid_driver_id)
    assert rec is not None
    assert rec.driver_id == valid_driver_id
    assert rec.external_subject == "user_clerk_123"
    assert rec.vehicle_id == vehicle_id
    assert rec.license_plate == "29A-123.45"

    # 2. Mock id (e.g. drv-sim-001) rejected
    assert dir_svc.get_active_driver(org_a, "drv-sim-001") is None

    # 3. Cross-tenant access rejected
    assert dir_svc.get_active_driver(org_b, valid_driver_id) is None

    # 4. Suspended driver rejected
    suspended_id = uuid4()
    dir_svc.register_driver(
        DriverRecord(
            driver_id=suspended_id,
            organization_id=org_a,
            principal_id=uuid4(),
            external_subject="user_clerk_suspended",
            display_name="Nguyen Suspended",
            email="suspended@example.com",
            account_status="suspended",
        )
    )
    assert dir_svc.get_active_driver(org_a, suspended_id) is None

    # 5. Closed driver rejected
    closed_id = uuid4()
    dir_svc.register_driver(
        DriverRecord(
            driver_id=closed_id,
            organization_id=org_a,
            principal_id=uuid4(),
            external_subject="user_clerk_closed",
            display_name="Nguyen Closed",
            email="closed@example.com",
            account_status="closed",
        )
    )
    assert dir_svc.get_active_driver(org_a, closed_id) is None

    # 6. Unlinked driver (no external_subject / clerk user) rejected
    unlinked_id = uuid4()
    dir_svc.register_driver(
        DriverRecord(
            driver_id=unlinked_id,
            organization_id=org_a,
            principal_id=uuid4(),
            external_subject=None,  # type: ignore[arg-type]
            display_name="Nguyen Unlinked",
            email=None,
            account_status="active",
        )
    )
    assert dir_svc.get_active_driver(org_a, unlinked_id) is None


def test_driver_directory_list_and_search_by_clerk_users():
    """Listing and searching filters strictly by tenant and active status."""
    dir_svc = InMemoryDriverDirectory()
    org_a = "018f2f4e-0000-7000-8000-000000000001"
    org_b = "018f2f4e-0000-7000-8000-00000000000b"

    d1 = uuid4()
    d2 = uuid4()
    d_other_org = uuid4()

    dir_svc.register_driver(
        DriverRecord(
            driver_id=d1,
            organization_id=org_a,
            principal_id=uuid4(),
            external_subject="user_clerk_1",
            display_name="Driver One",
            email="one@example.com",
            account_status="active",
        )
    )
    dir_svc.register_driver(
        DriverRecord(
            driver_id=d2,
            organization_id=org_a,
            principal_id=uuid4(),
            external_subject="user_clerk_2",
            display_name="Driver Two",
            email="two@example.com",
            account_status="active",
        )
    )
    dir_svc.register_driver(
        DriverRecord(
            driver_id=d_other_org,
            organization_id=org_b,
            principal_id=uuid4(),
            external_subject="user_clerk_3",
            display_name="Driver Foreign",
            email="foreign@example.com",
            account_status="active",
        )
    )

    # list_active_drivers returns only org_a drivers
    active_a = dir_svc.list_active_drivers(org_a)
    assert len(active_a) == 2
    assert {r.driver_id for r in active_a} == {d1, d2}

    # search_active_drivers_by_clerk_users matches clerk users to org drivers
    clerk_users = [
        {"id": "user_clerk_1", "email_addresses": [{"email_address": "one@example.com"}]},
        {"id": "user_clerk_3", "email_addresses": [{"email_address": "foreign@example.com"}]},
        {"id": "user_clerk_unknown", "email_addresses": [{"email_address": "unknown@example.com"}]},
    ]
    matched = dir_svc.search_active_drivers_by_clerk_users(org_a, clerk_users)
    assert len(matched) == 1
    assert matched[0].driver_id == d1
    assert matched[0].external_subject == "user_clerk_1"
