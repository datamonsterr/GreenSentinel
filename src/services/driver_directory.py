"""Driver Directory service: tenant isolation, Clerk linkage verification, and round-robin assignment (Issue #464).

Strict Tenancy and Linkage Rules:
- Drivers must belong to caller's organization_id.
- account_status must be 'active' (suspended or closed drivers are rejected).
- principal_id must be non-null and point to an active principal with a non-null external_subject (Clerk user ID).
- In-memory fake mode enables deterministic unit and integration tests without external database or network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar
from uuid import UUID

from src.services.clerk_directory import ClerkDirectoryClient

T = TypeVar("T")


@dataclass
class DriverRecord:
    driver_id: UUID
    organization_id: str
    principal_id: UUID
    external_subject: str  # Clerk user ID (e.g. user_2...)
    display_name: str
    email: str | None = None
    account_status: str = "active"
    partner_type: str = "fleet"
    is_synthetic: bool = False
    vehicle_id: UUID | None = None
    license_plate: str | None = None


def assign_drivers_round_robin(items: list[T], driver_ids: list[UUID]) -> list[tuple[T, UUID]]:
    """Assign driver_ids round-robin across items in order.

    Item i gets driver_ids[i % n], so counts differ by at most one.
    """
    if not driver_ids:
        raise ValueError("driver_ids must not be empty")
    n = len(driver_ids)
    return [(item, driver_ids[i % n]) for i, item in enumerate(items)]


class DriverDirectory:
    """Interface for driver directory operations."""

    def get_active_driver(self, organization_id: str, driver_id: UUID | str) -> DriverRecord | None:
        raise NotImplementedError

    def list_active_drivers(self, organization_id: str) -> list[DriverRecord]:
        raise NotImplementedError

    def search_active_drivers_by_clerk_users(
        self, organization_id: str, clerk_users: list[dict[str, Any]]
    ) -> list[DriverRecord]:
        raise NotImplementedError

    def register_driver(self, record: DriverRecord) -> DriverRecord:
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError


class InMemoryDriverDirectory(DriverDirectory):
    """In-memory driver directory for unit and integration testing without database."""

    def __init__(self) -> None:
        self._drivers: dict[tuple[str, str], DriverRecord] = {}

    def register_driver(self, record: DriverRecord) -> DriverRecord:
        org_id = str(record.organization_id)
        drv_id = str(record.driver_id)
        self._drivers[(org_id, drv_id)] = record
        return record

    def clear(self) -> None:
        self._drivers.clear()

    def get_active_driver(self, organization_id: str, driver_id: UUID | str) -> DriverRecord | None:
        org_id = str(organization_id)
        drv_id = str(driver_id)
        record = self._drivers.get((org_id, drv_id))
        if record is None:
            return None
        if record.account_status != "active":
            return None
        if not record.principal_id:
            return None
        if not record.external_subject or not str(record.external_subject).strip():
            return None
        return record

    def list_active_drivers(self, organization_id: str) -> list[DriverRecord]:
        org_id = str(organization_id)
        results: list[DriverRecord] = []
        for (rec_org, _), record in self._drivers.items():
            if rec_org == org_id:
                if (
                    record.account_status == "active"
                    and record.principal_id
                    and record.external_subject
                    and str(record.external_subject).strip()
                ):
                    results.append(record)
        return sorted(results, key=lambda r: str(r.driver_id))

    def search_active_drivers_by_clerk_users(
        self, organization_id: str, clerk_users: list[dict[str, Any]]
    ) -> list[DriverRecord]:
        active_drivers = self.list_active_drivers(organization_id)
        clerk_map: dict[str, dict[str, Any]] = {str(u.get("id")): u for u in clerk_users if u.get("id")}
        matched: list[DriverRecord] = []
        for drv in active_drivers:
            if drv.external_subject in clerk_map:
                u = clerk_map[drv.external_subject]
                email = ClerkDirectoryClient.extract_primary_email(u) or drv.email
                display_name = ClerkDirectoryClient.extract_display_name(u) or drv.display_name
                matched.append(
                    DriverRecord(
                        driver_id=drv.driver_id,
                        organization_id=drv.organization_id,
                        principal_id=drv.principal_id,
                        external_subject=drv.external_subject,
                        display_name=display_name,
                        email=email,
                        account_status=drv.account_status,
                        partner_type=drv.partner_type,
                        is_synthetic=drv.is_synthetic,
                        vehicle_id=drv.vehicle_id,
                        license_plate=drv.license_plate,
                    )
                )
        return matched


class HybridDriverDirectory(InMemoryDriverDirectory):
    """Authoritative database driver directory with in-memory fallback for test fixtures."""

    def _get_db(self) -> Any:
        try:
            from src.services.case_service import get_case_service

            cs = get_case_service()
            return cs._get_db_connection()
        except Exception:
            return None

    def get_active_driver(self, organization_id: str, driver_id: UUID | str) -> DriverRecord | None:
        org_id = str(organization_id)
        # Check in-memory registered fixture first
        mem_rec = super().get_active_driver(org_id, driver_id)
        if mem_rec is not None:
            return mem_rec

        try:
            drv_uuid = UUID(str(driver_id))
        except (ValueError, TypeError, AttributeError):
            return None

        conn = self._get_db()
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT d.id AS driver_id,
                               d.organization_id,
                               d.principal_id,
                               p.external_subject,
                               COALESCE(d.display_name, p.display_name, d.external_ref, d.id::text) AS display_name,
                               d.account_status,
                               d.partner_type,
                               d.is_synthetic,
                               v.id AS vehicle_id,
                               v.registration_ref AS license_plate
                        FROM app.drivers d
                        JOIN app.principals p ON d.principal_id = p.id
                        LEFT JOIN app.driver_vehicle_assignments dva
                               ON dva.driver_id = d.id AND (dva.effective_to IS NULL OR dva.effective_to > NOW())
                        LEFT JOIN app.vehicles v ON v.id = dva.vehicle_id
                        WHERE d.organization_id = %s
                          AND d.id = %s
                          AND d.account_status = 'active'
                          AND d.principal_id IS NOT NULL
                          AND p.external_subject IS NOT NULL
                          AND p.status = 'active';
                        """,
                        (org_id, str(drv_uuid)),
                    )
                    row = cur.fetchone()
                    if row:
                        r = dict(row)
                        return DriverRecord(
                            driver_id=UUID(str(r["driver_id"])),
                            organization_id=str(r["organization_id"]),
                            principal_id=UUID(str(r["principal_id"])),
                            external_subject=str(r["external_subject"]),
                            display_name=str(r["display_name"]),
                            account_status=str(r["account_status"]),
                            partner_type=str(r.get("partner_type") or "fleet"),
                            is_synthetic=bool(r.get("is_synthetic", False)),
                            vehicle_id=UUID(str(r["vehicle_id"])) if r.get("vehicle_id") else None,
                            license_plate=str(r["license_plate"]) if r.get("license_plate") else None,
                        )
            except Exception:
                pass
            finally:
                conn.close()

        # In-memory fixture fallback
        return super().get_active_driver(org_id, drv_uuid)

    def list_active_drivers(self, organization_id: str) -> list[DriverRecord]:
        org_id = str(organization_id)
        conn = self._get_db()
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT d.id AS driver_id,
                               d.organization_id,
                               d.principal_id,
                               p.external_subject,
                               COALESCE(d.display_name, p.display_name, d.external_ref, d.id::text) AS display_name,
                               d.account_status,
                               d.partner_type,
                               d.is_synthetic,
                               v.id AS vehicle_id,
                               v.registration_ref AS license_plate
                        FROM app.drivers d
                        JOIN app.principals p ON d.principal_id = p.id
                        LEFT JOIN app.driver_vehicle_assignments dva
                               ON dva.driver_id = d.id AND (dva.effective_to IS NULL OR dva.effective_to > NOW())
                        LEFT JOIN app.vehicles v ON v.id = dva.vehicle_id
                        WHERE d.organization_id = %s
                          AND d.account_status = 'active'
                          AND d.principal_id IS NOT NULL
                          AND p.external_subject IS NOT NULL
                          AND p.status = 'active'
                        ORDER BY d.created_at;
                        """,
                        (org_id,),
                    )
                    rows = cur.fetchall()
                    if rows:
                        results: list[DriverRecord] = []
                        for row in rows:
                            r = dict(row)
                            results.append(
                                DriverRecord(
                                    driver_id=UUID(str(r["driver_id"])),
                                    organization_id=str(r["organization_id"]),
                                    principal_id=UUID(str(r["principal_id"])),
                                    external_subject=str(r["external_subject"]),
                                    display_name=str(r["display_name"]),
                                    account_status=str(r["account_status"]),
                                    partner_type=str(r.get("partner_type") or "fleet"),
                                    is_synthetic=bool(r.get("is_synthetic", False)),
                                    vehicle_id=UUID(str(r["vehicle_id"])) if r.get("vehicle_id") else None,
                                    license_plate=str(r["license_plate"]) if r.get("license_plate") else None,
                                )
                            )
                        mem_drivers = super().list_active_drivers(org_id)
                        db_ids = {d.driver_id for d in results}
                        for md in mem_drivers:
                            if md.driver_id not in db_ids:
                                results.append(md)
                        return results
            except Exception:
                pass
            finally:
                conn.close()

        # In-memory fixture fallback
        return super().list_active_drivers(org_id)


_GLOBAL_DRIVER_DIRECTORY: DriverDirectory = HybridDriverDirectory()


def get_driver_directory() -> DriverDirectory:
    """Return globally configured driver directory."""
    return _GLOBAL_DRIVER_DIRECTORY


def set_driver_directory(directory: DriverDirectory) -> None:
    """Set custom driver directory (e.g. for testing)."""
    global _GLOBAL_DRIVER_DIRECTORY
    _GLOBAL_DRIVER_DIRECTORY = directory
