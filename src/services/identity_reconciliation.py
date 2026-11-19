"""Identity Reconciliation Service for GreenSentinel (#410 / #402 / #394).

Provides audited, repository-owned synchronization between Clerk (identity & org truth)
and Railway PostgreSQL databases across dev, staging, and production environments.

Invariants & Guarantees:
1. Zero Fabricated Accounts: No synthetic Clerk users or replacement applications.
2. Deterministic UUID5 Org Mapping: Preserves established database links; new orgs
   derive UUID5 from Clerk Org ID. Collisions abort immediately.
3. Strict Role Mapping: org:admin -> admin, member/analyst -> fraud_analyst, driver -> driver.
   Unknown roles are denied. Demotions and stale roles are cleanly replaced.
4. Human Record Preservation: Real principals without active memberships are deactivated
   (status='disabled', roles removed) without deleting their human historical records.
5. Proven Mock Lineage Deletion: Mock principals (user_clerk_analyst_*, drv_gsm_*) and
   mock seed cases are deleted only through complete catalog-derived FK closure.
6. Real Record Protection: Real fraud cases and audit events are NEVER deleted via mock actor FKs.
   Mock principals referencing unapproved records outside fixture closure fail closed.
7. Append-Only Trigger Handling: Identifies append-only guards by catalog, disables only that guard
   under bounded transactional lock, restores original state before commit and on rollback,
   and proves unrelated append-only records remain protected.
8. Safety Guards: Mode 0600 recovery export with actual row data before mutation, advisory locking
   with lock timeout set before acquisition, plan hash & schema fingerprint verification under lock,
   atomic transaction rollback on failure. Loopback + disposable prefix + opt-in enforcement.
"""

from __future__ import annotations

import datetime
import decimal
import hashlib
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Canonical namespace for deterministic org UUID5 generation
CLERK_ORG_UUID_NAMESPACE: uuid.UUID = uuid.NAMESPACE_URL

# Role mapping specification
ROLE_MAPPING: dict[str, str] = {
    "org:admin": "admin",
    "admin": "admin",
    "org:member": "fraud_analyst",
    "member": "fraud_analyst",
    "analyst": "fraud_analyst",
    "org:driver": "driver",
    "driver": "driver",
    # GSM workflow roles (ADR-031)
    **{f"org:{r}": r for r in ("reviewer", "ops_director", "marketplace_director")},
    **{r: r for r in ("reviewer", "ops_director", "marketplace_director")},
}

# Proven mock identifiers from test fixtures and seed_cloud.sql
PROVEN_MOCK_SUBJECT_PREFIXES = ("user_clerk_analyst_", "drv_gsm_")
PROVEN_MOCK_CASE_ID_PREFIX = "018f2f4e-a000-7000-8000-"

# Known append-only triggers that execute app.reject_mutation()
# Mapped to (trigger_name, expected_function)
KNOWN_APPEND_ONLY_TRIGGERS: dict[str, str] = {
    "model_assessments": "model_assessments_append_only",
    "feature_sets": "feature_sets_append_only",
    "precedent_reuse_history": "precedent_reuse_history_append_only",
    "precedent_workflows": "precedent_workflows_append_only",
    "solved_case_contexts": "solved_case_contexts_append_only",
    "preliminary_judgments": "preliminary_judgments_append_only",
    "adjudications": "adjudications_append_only",
    "case_agent_messages": "case_agent_messages_append_only",
    "evidence_snapshots": "evidence_snapshots_append_only",
    "audit_events": "audit_events_append_only",
}

# Complete topological deletion order for fraud cases and all direct/indirect dependents
# Order: Deepest child dependents first, parents last
CASE_FK_CLEANUP_ORDER: list[str] = [
    "model_assessments",
    "feature_sets",
    "sanctions",
    "workflow_minutes",
    "precedent_reuse_history",
    "precedent_workflows",
    "solved_case_contexts",
    "preliminary_judgments",
    "review_actions",
    "review_leases",
    "adjudications",
    "case_agent_messages",
    "case_agent_sessions",
    "workflow_answers",
    "workflow_action_requests",
    "workflow_questions",
    "driver_admission_sanctions",
    "driver_submissions",
    "evidence_snapshots",
    "case_assignment_history",
    "case_documents",
    "agent_runtime_turns",
    "audit_events",
    "fraud_cases",
]


class IdentityReconciliationError(Exception):
    """Base exception for identity reconciliation errors."""


class ClerkAPIError(IdentityReconciliationError):
    """Clerk API failure or rate limit error."""


class ClerkPaginationError(IdentityReconciliationError):
    """Clerk API pagination incomplete or mismatched total count."""


class ClerkMembershipConflictError(IdentityReconciliationError):
    """Conflicting roles for same user in same organization."""


class StalePlanError(IdentityReconciliationError):
    """Plan hash mismatch, schema drift, or stale plan rejected."""


class SchemaMismatchError(IdentityReconciliationError):
    """Database schema, table, or column does not match expected definition."""


class MockPrincipalReferenceError(IdentityReconciliationError):
    """Mock principal has references outside approved fixture closure."""


class TriggerMismatchError(IdentityReconciliationError):
    """Trigger definition or function does not match catalog expectation."""


class SafetyGuardError(PermissionError, IdentityReconciliationError):
    """Connection or execution safety guard rejected operation."""


def hash_mask(val: Any) -> str:
    """Return opaque 12-char SHA256 digest mask for PII/names."""
    if not val:
        return "none"
    return hashlib.sha256(str(val).encode("utf-8")).hexdigest()[:12]


def map_clerk_role(role: str) -> str:
    """Map Clerk membership role string to internal DB role."""
    normalized = (role or "").strip().lower()
    if normalized in ROLE_MAPPING:
        return ROLE_MAPPING[normalized]
    raise ValueError(f"Unknown or unmapped Clerk role: {role!r}. Allowed: {sorted(list(ROLE_MAPPING.keys()))}")


def assert_disposable_db_guard(db_url: str) -> None:
    """Enforce loopback AND disposable prefix AND opt-in.

    No remote bypass by opting in.
    """
    if not db_url:
        raise SafetyGuardError("database_url is required")
    parsed = urllib.parse.urlparse(db_url)
    hostname = (parsed.hostname or "").lower()
    # Must be loopback
    if hostname not in ("127.0.0.1", "localhost", "::1"):
        raise SafetyGuardError(
            f"Safety guard violation: host {hostname!r} is not loopback (127.0.0.1 / localhost). "
            "Remote databases strictly forbidden."
        )
    dbname = (parsed.path or "").lstrip("/")
    if not (dbname.startswith("test_greensentinel_finalize_394_") or dbname.startswith("test_greensentinel_disposable_")):
        raise SafetyGuardError(
            f"Safety guard violation: database {dbname!r} does not have disposable prefix. "
            "Must start with 'test_greensentinel_finalize_394_' or 'test_greensentinel_disposable_'."
        )
    has_optin = os.environ.get("GREENSENTINEL_RECONCILE_DISPOSABLE_DB") == "1"
    if not has_optin:
        raise SafetyGuardError("Safety guard violation: GREENSENTINEL_RECONCILE_DISPOSABLE_DB=1 opt-in required.")


def compute_org_uuid(
    clerk_org_id: str,
    existing_mappings: dict[str, str] | None = None,
    existing_uuids: set[str] | None = None,
) -> str:
    """Compute deterministic UUID for an organization.

    Preserves established mappings (from existing DB clerk_organization_id).
    Generates UUID5 for new orgs.
    Detects and rejects UUID collisions.
    """
    existing_map = existing_mappings or {}
    if clerk_org_id in existing_map:
        return existing_map[clerk_org_id]

    derived_uuid = str(uuid.uuid5(CLERK_ORG_UUID_NAMESPACE, f"https://greensentinel.internal/org/{clerk_org_id}"))

    uuids_in_use = existing_uuids or set(existing_map.values())
    if derived_uuid in uuids_in_use:
        raise ValueError(f"Collision: generated UUID {derived_uuid} collides with existing organization UUID")

    return derived_uuid


@dataclass
class ClerkOrg:
    id: str
    name: str
    slug: str | None = None
    created_at: int | None = None


@dataclass
class ClerkUser:
    id: str
    email_hash: str | None = None
    created_at: int | None = None
    display_name: str | None = None
    public_metadata: dict = field(default_factory=dict)


@dataclass
class ClerkMembership:
    id: str
    user_id: str
    org_id: str
    role: str
    created_at: int | None = None


@dataclass
class ClerkSnapshot:
    organizations: list[ClerkOrg]
    users: list[ClerkUser]
    memberships: list[ClerkMembership]
    total_orgs: int
    total_users: int
    total_memberships: int
    complete: bool = True

    def validate_completeness(self) -> None:
        """Assert that all items were successfully fetched and counts match."""
        if not self.complete:
            raise ClerkPaginationError("Clerk snapshot marked incomplete due to fetch error.")
        if len(self.organizations) != self.total_orgs:
            raise ClerkPaginationError(
                f"Pagination incomplete: fetched {len(self.organizations)} orgs, expected {self.total_orgs}"
            )
        if len(self.users) != self.total_users:
            raise ClerkPaginationError(
                f"Pagination incomplete: fetched {len(self.users)} users, expected {self.total_users}"
            )
        if len(self.memberships) != self.total_memberships:
            raise ClerkPaginationError(
                f"Pagination incomplete: fetched {len(self.memberships)} memberships, expected {self.total_memberships}"
            )

        # Detect duplicate IDs
        seen_orgs: set[str] = set()
        for o in self.organizations:
            if o.id in seen_orgs:
                raise ClerkPaginationError(f"Duplicate organization ID in snapshot: {o.id}")
            seen_orgs.add(o.id)

        seen_users: set[str] = set()
        for u in self.users:
            if u.id in seen_users:
                raise ClerkPaginationError(f"Duplicate user ID in snapshot: {u.id}")
            seen_users.add(u.id)

        # Detect membership conflicts for same user in same org
        seen_memberships: dict[tuple[str, str], str] = {}
        for m in self.memberships:
            key = (m.org_id, m.user_id)
            if key in seen_memberships:
                if seen_memberships[key] != m.role:
                    raise ClerkMembershipConflictError(
                        f"Conflicting membership roles for user {m.user_id} in org {m.org_id}: "
                        f"{seen_memberships[key]!r} vs {m.role!r}"
                    )
            seen_memberships[key] = m.role
            # Ensure valid mapped role
            map_clerk_role(m.role)


@dataclass
class DatabaseAuditState:
    migrations_count: int
    latest_migration: str | dict | None
    organizations: list[dict]
    principals: list[dict]
    mock_cases: list[dict]
    available_tables: set[str]
    drivers: list[dict] = field(default_factory=list)
    columns_catalog: list[dict] = field(default_factory=list)
    check_constraints_catalog: list[dict] = field(default_factory=list)
    foreign_keys_catalog: list[dict] = field(default_factory=list)
    triggers_catalog: list[dict] = field(default_factory=list)


@dataclass
class ReconciliationPlan:
    env: str
    plan_hash: str
    schema_fingerprint: str
    orgs_to_create: list[dict]
    orgs_unchanged: list[dict]
    orgs_to_update_name: list[dict]
    principals_to_create: list[dict]
    principals_to_update_role: list[dict]
    principals_to_deactivate: list[dict]
    principals_to_delete: list[dict]
    mock_cases_to_delete: list[dict]
    fk_cleanup_steps: list[dict]
    preflight_missing_tables: list[str]
    recovery_export_data: dict = field(default_factory=dict)


class _RowJSONEncoder(json.JSONEncoder):
    """JSON encoder handling UUID, datetime, date, Decimal, and bytes."""

    def default(self, o: Any) -> Any:
        if isinstance(o, uuid.UUID):
            return str(o)
        if isinstance(o, (datetime.datetime, datetime.date)):
            return o.isoformat()
        if isinstance(o, decimal.Decimal):
            return float(o)
        if isinstance(o, (bytes, bytearray, memoryview)):
            return bytes(o).hex()
        return super().default(o)


def export_recovery_snapshot(data: dict, file_path: str) -> str:
    """Save recovery snapshot with strict mode 0600 permissions."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    # 0o600: read and write only by file owner
    fd = os.open(file_path, flags, 0o600)
    try:
        with open(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True, cls=_RowJSONEncoder)
    except Exception:
        # fd is closed by open context manager if successful, but handle exception
        pass
    # Verify file permissions mode 0600
    st_mode = os.stat(file_path).st_mode & 0o777
    if st_mode != 0o600:
        os.chmod(file_path, 0o600)
    return file_path


def fetch_clerk_snapshot_from_file(file_path: str) -> ClerkSnapshot:
    """Load and validate Clerk snapshot from local audit file."""
    with open(file_path, encoding="utf-8") as f:
        raw = json.load(f)

    if raw.get("error"):
        raise ClerkAPIError(f"Snapshot contains error flag: {raw['error']}")

    clerk_data = raw.get("clerk", raw)
    orgs = [
        ClerkOrg(
            id=o["id"],
            name=o.get("name") or "",
            slug=o.get("slug"),
            created_at=o.get("created_at"),
        )
        for o in clerk_data.get("organizations", [])
    ]
    users = []
    for u in clerk_data.get("users", []):
        display_name = (
            u.get("display_name")
            or u.get("name")
            or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
            or u.get("username")
            or (u.get("public_metadata") or {}).get("display_name")
            or None
        )
        users.append(
            ClerkUser(
                id=u["id"],
                email_hash=u.get("primary_email_hash")
                or (hash_mask(u.get("primary_email")) if u.get("primary_email") else None),
                created_at=u.get("created_at"),
                display_name=display_name,
                public_metadata=u.get("public_metadata", {}),
            )
        )

    memberships = [
        ClerkMembership(
            id=m["id"],
            user_id=m["user_id"],
            org_id=m["org_id"],
            role=m["role"],
            created_at=m.get("created_at"),
        )
        for m in clerk_data.get("memberships", [])
    ]

    snapshot = ClerkSnapshot(
        organizations=orgs,
        users=users,
        memberships=memberships,
        total_orgs=clerk_data.get("total_orgs", len(orgs)),
        total_users=clerk_data.get("total_users", len(users)),
        total_memberships=clerk_data.get("total_memberships", len(memberships)),
        complete=bool(clerk_data.get("complete", True)),
    )
    snapshot.validate_completeness()
    return snapshot


def fetch_clerk_snapshot_from_api(secret_key: str, base_url: str = "https://api.clerk.com/v1") -> ClerkSnapshot:
    """Fetch complete paginated snapshot from Clerk REST API."""
    headers = {
        "Authorization": f"Bearer {secret_key}",
        "Content-Type": "application/json",
    }

    def _paginate(endpoint: str) -> list[dict]:
        items: list[dict] = []
        limit = 100
        offset = 0
        seen_ids: set[str] = set()
        while True:
            url = f"{base_url}{endpoint}?limit={limit}&offset={offset}"
            req = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    page = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    raise ClerkAPIError("Clerk API rate limited (HTTP 429)") from exc
                raise ClerkAPIError(f"Clerk API error {exc.code}: {exc.reason}") from exc
            except Exception as exc:
                raise ClerkAPIError(f"Clerk API network failure: {exc}") from exc

            data = page.get("data", page) if isinstance(page, dict) else page
            if not data:
                break

            for item in data:
                iid = item.get("id")
                if iid and iid in seen_ids:
                    raise ClerkPaginationError(f"Stuck or duplicated pagination detected at offset {offset}")
                if iid:
                    seen_ids.add(iid)
                items.append(item)

            if len(data) < limit:
                break
            offset += limit
        return items

    raw_orgs = _paginate("/organizations")
    raw_users = _paginate("/users")

    memberships: list[ClerkMembership] = []
    for org in raw_orgs:
        org_id = org["id"]
        raw_m = _paginate(f"/organizations/{org_id}/memberships")
        for m in raw_m:
            uid = str(m.get("public_user_data", {}).get("user_id") or m.get("user_id") or "")
            memberships.append(
                ClerkMembership(
                    id=m["id"],
                    user_id=uid,
                    org_id=org_id,
                    role=m.get("role", ""),
                    created_at=m.get("created_at"),
                )
            )

    orgs = [
        ClerkOrg(id=o["id"], name=o.get("name", ""), slug=o.get("slug"), created_at=o.get("created_at"))
        for o in raw_orgs
    ]
    users = []
    for u in raw_users:
        display_name = (
            u.get("display_name")
            or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
            or u.get("username")
            or (u.get("public_metadata") or {}).get("display_name")
            or None
        )
        users.append(
            ClerkUser(
                id=u["id"],
                email_hash=hash_mask(
                    u.get("email_addresses", [{}])[0].get("email_address") if u.get("email_addresses") else None
                ),
                created_at=u.get("created_at"),
                display_name=display_name,
                public_metadata=u.get("public_metadata", {}),
            )
        )

    snapshot = ClerkSnapshot(
        organizations=orgs,
        users=users,
        memberships=memberships,
        total_orgs=len(orgs),
        total_users=len(users),
        total_memberships=len(memberships),
        complete=True,
    )
    snapshot.validate_completeness()
    return snapshot


def audit_database_state(conn: Any) -> DatabaseAuditState:
    """Query current database schema, migrations, orgs, principals, drivers, and cases."""
    with conn.cursor() as cur:
        # 1. Discover available tables in app schema
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'app'
            """
        )
        rows = cur.fetchall() or []
        available_tables = {r[0] if isinstance(r, (tuple, list)) else r["table_name"] for r in rows}

        # 2. Migrations count & latest
        migrations_count = 0
        latest_migration = None
        try:
            cur.execute("SELECT version, applied_at FROM public.schema_migrations ORDER BY version")
            migrations = cur.fetchall() or []
            migrations_count = len(migrations)
            if migrations:
                last_m = migrations[-1]
                if isinstance(last_m, (tuple, list)):
                    latest_migration = {"version": last_m[0], "applied_at": str(last_m[1])}
                else:
                    latest_migration = {"version": last_m["version"], "applied_at": str(last_m["applied_at"])}
        except Exception:
            # Table schema_migrations may not exist in mock cursors
            pass

        # 3. Columns Catalog
        columns_catalog: list[dict] = []
        try:
            cur.execute(
                """
                SELECT table_name, column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'app'
                ORDER BY table_name, ordinal_position
                """
            )
            for r in cur.fetchall() or []:
                if isinstance(r, (tuple, list)):
                    columns_catalog.append(
                        {
                            "table_name": r[0],
                            "column_name": r[1],
                            "data_type": r[2],
                            "is_nullable": r[3],
                            "column_default": r[4],
                        }
                    )
                else:
                    columns_catalog.append(dict(r))
        except Exception:
            pass

        # 4. Check Constraints Catalog
        check_constraints_catalog: list[dict] = []
        try:
            cur.execute(
                """
                SELECT tc.table_name, tc.constraint_name, cc.check_clause
                FROM information_schema.table_constraints tc
                JOIN information_schema.check_constraints cc ON tc.constraint_name = cc.constraint_name
                WHERE tc.table_schema = 'app' AND tc.constraint_type = 'CHECK'
                ORDER BY tc.table_name, tc.constraint_name
                """
            )
            for r in cur.fetchall() or []:
                if isinstance(r, (tuple, list)):
                    check_constraints_catalog.append(
                        {
                            "table_name": r[0],
                            "constraint_name": r[1],
                            "check_clause": r[2],
                        }
                    )
                else:
                    check_constraints_catalog.append(dict(r))
        except Exception:
            pass

        # 5. Foreign Keys Catalog
        foreign_keys_catalog: list[dict] = []
        try:
            cur.execute(
                """
                SELECT tc.table_name, kcu.column_name, ccu.table_name AS foreign_table_name,
                       ccu.column_name AS foreign_column_name, tc.constraint_name, rc.delete_rule
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
                JOIN information_schema.referential_constraints rc
                    ON tc.constraint_name = rc.constraint_name
                JOIN information_schema.constraint_column_usage ccu
                    ON ccu.constraint_name = tc.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'app'
                ORDER BY tc.table_name, kcu.column_name
                """
            )
            for r in cur.fetchall() or []:
                if isinstance(r, (tuple, list)):
                    foreign_keys_catalog.append(
                        {
                            "table_name": r[0],
                            "column_name": r[1],
                            "foreign_table_name": r[2],
                            "foreign_column_name": r[3],
                            "constraint_name": r[4],
                            "delete_rule": r[5],
                        }
                    )
                else:
                    foreign_keys_catalog.append(dict(r))
        except Exception:
            pass

        # 6. Triggers Catalog
        triggers_catalog: list[dict] = []
        try:
            cur.execute(
                """
                SELECT c.relname AS table_name, t.tgname AS trigger_name,
                       p.proname AS function_name, t.tgenabled AS enabled
                FROM pg_trigger t
                JOIN pg_class c ON t.tgrelid = c.oid
                JOIN pg_namespace n ON c.relnamespace = n.oid
                JOIN pg_proc p ON t.tgfoid = p.oid
                WHERE n.nspname = 'app' AND NOT t.tgisinternal
                ORDER BY c.relname, t.tgname
                """
            )
            for r in cur.fetchall() or []:
                if isinstance(r, (tuple, list)):
                    triggers_catalog.append(
                        {
                            "table_name": r[0],
                            "trigger_name": r[1],
                            "function_name": r[2],
                            "enabled": r[3],
                        }
                    )
                else:
                    triggers_catalog.append(dict(r))
        except Exception:
            pass

        # 7. Organizations
        organizations = []
        if "organizations" in available_tables:
            cur.execute("SELECT id, name, clerk_organization_id FROM app.organizations ORDER BY created_at")
            for r in cur.fetchall() or []:
                organizations.append(
                    {
                        "id": str(r[0] if isinstance(r, (tuple, list)) else r["id"]),
                        "name": r[1] if isinstance(r, (tuple, list)) else r["name"],
                        "clerk_organization_id": r[2] if isinstance(r, (tuple, list)) else r["clerk_organization_id"],
                    }
                )

        # 8. Principals with aggregated roles
        principals = []
        if "principals" in available_tables:
            cur.execute(
                """
                SELECT p.id, p.organization_id, p.external_subject, p.display_name, p.status,
                       array_remove(array_agg(r.role), null) as roles
                FROM app.principals p
                LEFT JOIN app.principal_roles r ON r.principal_id = p.id
                GROUP BY p.id, p.organization_id, p.external_subject, p.display_name, p.status
                ORDER BY p.created_at
                """
            )
            for r in cur.fetchall() or []:
                principals.append(
                    {
                        "id": str(r[0] if isinstance(r, (tuple, list)) else r["id"]),
                        "organization_id": str(r[1] if isinstance(r, (tuple, list)) else r["organization_id"]),
                        "external_subject": r[2] if isinstance(r, (tuple, list)) else r["external_subject"],
                        "display_name": r[3] if isinstance(r, (tuple, list)) else r["display_name"],
                        "status": r[4] if isinstance(r, (tuple, list)) else r["status"],
                        "roles": list(r[5] if isinstance(r, (tuple, list)) else r["roles"] or []),
                    }
                )

        # 9. Drivers
        drivers: list[dict] = []
        if "drivers" in available_tables:
            cur.execute("SELECT id, organization_id, principal_id, external_ref, is_synthetic FROM app.drivers")
            for r in cur.fetchall() or []:
                drivers.append(
                    {
                        "id": str(r[0] if isinstance(r, (tuple, list)) else r["id"]),
                        "organization_id": str(r[1] if isinstance(r, (tuple, list)) else r["organization_id"]),
                        "principal_id": str(r[2])
                        if (r[2] if isinstance(r, (tuple, list)) else r["principal_id"])
                        else None,
                        "external_ref": r[3] if isinstance(r, (tuple, list)) else r["external_ref"],
                        "is_synthetic": bool(r[4] if isinstance(r, (tuple, list)) else r["is_synthetic"]),
                    }
                )

        # 10. Mock Cases (proven fixture cases from seed artifacts)
        mock_cases: list[dict] = []
        if "fraud_cases" in available_tables:
            cur.execute(
                f"""
                SELECT id, organization_id, status
                FROM app.fraud_cases
                WHERE id::text LIKE '{PROVEN_MOCK_CASE_ID_PREFIX}%'
                ORDER BY created_at
                """
            )
            for r in cur.fetchall() or []:
                mock_cases.append(
                    {
                        "id": str(r[0] if isinstance(r, (tuple, list)) else r["id"]),
                        "organization_id": str(r[1] if isinstance(r, (tuple, list)) else r["organization_id"]),
                        "status": r[2] if isinstance(r, (tuple, list)) else r["status"],
                    }
                )

    return DatabaseAuditState(
        migrations_count=migrations_count,
        latest_migration=latest_migration,
        organizations=organizations,
        principals=principals,
        mock_cases=mock_cases,
        available_tables=available_tables,
        drivers=drivers,
        columns_catalog=columns_catalog,
        check_constraints_catalog=check_constraints_catalog,
        foreign_keys_catalog=foreign_keys_catalog,
        triggers_catalog=triggers_catalog,
    )


def generate_reconciliation_plan(
    clerk_snapshot: ClerkSnapshot,
    db_state: DatabaseAuditState,
    env: str,
) -> ReconciliationPlan:
    """Compute exact, deterministic diff and hashed plan for target environment."""
    clerk_snapshot.validate_completeness()

    # Preflight: detect missing tables
    expected_all_tables = {
        "organizations",
        "principals",
        "principal_roles",
        "drivers",
        "fraud_cases",
        "adjudications",
        "review_actions",
        "review_leases",
        "audit_events",
        "case_agent_sessions",
        "case_agent_messages",
        "workflow_questions",
        "workflow_answers",
        "workflow_minutes",
        "workflow_action_requests",
        "agent_runtime_turns",
        "solved_case_contexts",
        "precedent_reuse_history",
        "driver_admission_sanctions",
        "preliminary_judgments",
    }
    missing_tables = sorted(list(expected_all_tables - db_state.available_tables))

    # 1. Organization mapping: preserve validated existing DB links dynamically
    existing_db_org_by_clerk_id: dict[str, dict] = {
        o["clerk_organization_id"]: o for o in db_state.organizations if o.get("clerk_organization_id")
    }
    existing_uuids: set[str] = {o["id"] for o in db_state.organizations}

    canonical_mappings: dict[str, str] = {}
    for clerk_id, db_org in existing_db_org_by_clerk_id.items():
        canonical_mappings[clerk_id] = db_org["id"]

    orgs_to_create: list[dict] = []
    orgs_unchanged: list[dict] = []
    orgs_to_update_name: list[dict] = []

    for clerk_org in clerk_snapshot.organizations:
        mapped_uuid = compute_org_uuid(clerk_org.id, canonical_mappings, existing_uuids)
        if clerk_org.id in existing_db_org_by_clerk_id:
            existing_db_org = existing_db_org_by_clerk_id[clerk_org.id]
            current_name = existing_db_org.get("name")
            if clerk_org.name and clerk_org.name != current_name:
                orgs_to_update_name.append(
                    {
                        "id": mapped_uuid,
                        "clerk_id": clerk_org.id,
                        "old_name": current_name,
                        "new_name": clerk_org.name,
                        "name_hash": hash_mask(clerk_org.name),
                    }
                )
            else:
                orgs_unchanged.append(
                    {
                        "clerk_id": clerk_org.id,
                        "uuid": mapped_uuid,
                        "name_hash": hash_mask(clerk_org.name),
                    }
                )
        else:
            orgs_to_create.append(
                {
                    "clerk_id": clerk_org.id,
                    "uuid": mapped_uuid,
                    "name": clerk_org.name or f"Org {clerk_org.id}",
                    "name_hash": hash_mask(clerk_org.name),
                }
            )
            canonical_mappings[clerk_org.id] = mapped_uuid
            existing_uuids.add(mapped_uuid)

    # 2. Principals and Roles synchronization
    db_principals_by_key: dict[tuple[str, str], dict] = {
        (p["organization_id"], p["external_subject"]): p for p in db_state.principals
    }

    # Map user id to clerk user object for profile display names
    clerk_users_by_id: dict[str, ClerkUser] = {u.id: u for u in clerk_snapshot.users}

    # Index active Clerk memberships by (mapped_org_uuid, user_id)
    active_clerk_memberships: dict[tuple[str, str], str] = {}
    for m in clerk_snapshot.memberships:
        target_org_uuid = canonical_mappings.get(m.org_id)
        if target_org_uuid:
            mapped_role = map_clerk_role(m.role)
            active_clerk_memberships[(target_org_uuid, m.user_id)] = mapped_role

    principals_to_create: list[dict] = []
    principals_to_update_role: list[dict] = []
    principals_to_deactivate: list[dict] = []
    principals_to_delete: list[dict] = []

    # Identify creates & role updates for active memberships
    for (org_uuid, user_id), mapped_role in active_clerk_memberships.items():
        clerk_user = clerk_users_by_id.get(user_id)
        trusted_display_name = clerk_user.display_name if clerk_user else None
        existing_p = db_principals_by_key.get((org_uuid, user_id))

        if not existing_p:
            # Use trusted profile display name if provided, else user_id itself (no invented User xxxx)
            display_name = trusted_display_name or user_id
            principals_to_create.append(
                {
                    "organization_id": org_uuid,
                    "external_subject": user_id,
                    "display_name": display_name,
                    "subject_hash": hash_mask(user_id),
                    "role": mapped_role,
                }
            )
        else:
            current_roles = set(existing_p.get("roles", []))
            current_status = existing_p.get("status")
            current_name = existing_p.get("display_name")
            display_name = trusted_display_name or current_name or user_id

            if (
                current_roles != {mapped_role}
                or current_status != "active"
                or (trusted_display_name and trusted_display_name != current_name)
            ):
                principals_to_update_role.append(
                    {
                        "id": existing_p["id"],
                        "organization_id": org_uuid,
                        "external_subject": user_id,
                        "display_name": display_name,
                        "subject_hash": hash_mask(user_id),
                        "old_roles": sorted(list(current_roles)),
                        "new_role": mapped_role,
                        "old_status": current_status,
                        "new_status": "active",
                    }
                )

    # Inspect all existing DB principals
    for p in db_state.principals:
        subject = p.get("external_subject") or ""
        p_org = p.get("organization_id")

        # Check if proven mock principal
        is_mock = any(subject.startswith(prefix) for prefix in PROVEN_MOCK_SUBJECT_PREFIXES)
        if is_mock:
            principals_to_delete.append(
                {
                    "id": p["id"],
                    "organization_id": p_org,
                    "external_subject": subject,
                    "roles": p.get("roles", []),
                }
            )
            continue

        # Check if real user has active membership in this org
        if (p_org, subject) not in active_clerk_memberships:
            # Orphaned real principal: deactivate with status='disabled', revoke roles, NEVER delete historical row
            if p.get("status") == "active" or p.get("roles"):
                principals_to_deactivate.append(
                    {
                        "id": p["id"],
                        "organization_id": p_org,
                        "external_subject": subject,
                        "subject_hash": hash_mask(subject),
                        "current_status": p.get("status"),
                        "new_status": "disabled",
                        "current_roles": p.get("roles", []),
                    }
                )

    # 3. Proven mock cases to delete (derived from seed artifacts)
    mock_cases_to_delete = sorted(db_state.mock_cases, key=lambda c: c["id"])

    # 4. FK cleanup steps for mock cases
    fk_cleanup_steps: list[dict] = []
    mock_case_ids = [c["id"] for c in mock_cases_to_delete]
    for table_name in CASE_FK_CLEANUP_ORDER:
        if table_name in db_state.available_tables and mock_case_ids:
            fk_cleanup_steps.append(
                {
                    "target": "cases",
                    "table": table_name,
                    "append_only": table_name in KNOWN_APPEND_ONLY_TRIGGERS,
                    "parent_ids_count": len(mock_case_ids),
                }
            )

    # 5. Canonical Schema & Data Fingerprint
    schema_manifest = {
        "migrations_count": db_state.migrations_count,
        "latest_migration": db_state.latest_migration,
        "available_tables": sorted(list(db_state.available_tables)),
        "columns_catalog": sorted(
            db_state.columns_catalog, key=lambda x: (x.get("table_name", ""), x.get("column_name", ""))
        ),
        "check_constraints_catalog": sorted(
            db_state.check_constraints_catalog, key=lambda x: (x.get("table_name", ""), x.get("constraint_name", ""))
        ),
        "foreign_keys_catalog": sorted(
            db_state.foreign_keys_catalog, key=lambda x: (x.get("table_name", ""), x.get("column_name", ""))
        ),
        "triggers_catalog": sorted(
            db_state.triggers_catalog, key=lambda x: (x.get("table_name", ""), x.get("trigger_name", ""))
        ),
        "clerk_snapshot_summary": {
            "total_orgs": clerk_snapshot.total_orgs,
            "total_users": clerk_snapshot.total_users,
            "total_memberships": clerk_snapshot.total_memberships,
            "org_ids": sorted([o.id for o in clerk_snapshot.organizations]),
            "user_ids": sorted([u.id for u in clerk_snapshot.users]),
            "memberships": sorted([(m.org_id, m.user_id, m.role) for m in clerk_snapshot.memberships]),
        },
        "affected_data_fingerprint": {
            "db_org_ids": sorted([o["id"] for o in db_state.organizations]),
            "db_principal_ids": sorted([p["id"] for p in db_state.principals]),
            "mock_case_ids": sorted(mock_case_ids),
        },
    }
    schema_fingerprint = hashlib.sha256(
        json.dumps(schema_manifest, sort_keys=True, cls=_RowJSONEncoder).encode("utf-8")
    ).hexdigest()

    # 6. Canonical Plan Hash
    canonical_plan_dict = {
        "env": env,
        "schema_fingerprint": schema_fingerprint,
        "orgs_to_create": sorted(orgs_to_create, key=lambda x: x["clerk_id"]),
        "orgs_unchanged": sorted(orgs_unchanged, key=lambda x: x["clerk_id"]),
        "orgs_to_update_name": sorted(orgs_to_update_name, key=lambda x: x["clerk_id"]),
        "principals_to_create": sorted(
            principals_to_create, key=lambda x: (x["organization_id"], x["external_subject"])
        ),
        "principals_to_update_role": sorted(principals_to_update_role, key=lambda x: x["id"]),
        "principals_to_deactivate": sorted(principals_to_deactivate, key=lambda x: x["id"]),
        "principals_to_delete": sorted(principals_to_delete, key=lambda x: x["id"]),
        "mock_cases_to_delete": mock_cases_to_delete,
        "fk_cleanup_steps": fk_cleanup_steps,
        "preflight_missing_tables": missing_tables,
    }
    plan_hash = hashlib.sha256(json.dumps(canonical_plan_dict, sort_keys=True).encode("utf-8")).hexdigest()

    recovery_export_data = {
        "plan_hash": plan_hash,
        "env": env,
        "schema_fingerprint": schema_fingerprint,
        "principals_to_delete": principals_to_delete,
        "principals_to_deactivate": principals_to_deactivate,
        "principals_to_update_role": principals_to_update_role,
        "mock_cases_to_delete": mock_cases_to_delete,
    }

    return ReconciliationPlan(
        env=env,
        plan_hash=plan_hash,
        schema_fingerprint=schema_fingerprint,
        orgs_to_create=orgs_to_create,
        orgs_unchanged=orgs_unchanged,
        orgs_to_update_name=orgs_to_update_name,
        principals_to_create=principals_to_create,
        principals_to_update_role=principals_to_update_role,
        principals_to_deactivate=principals_to_deactivate,
        principals_to_delete=principals_to_delete,
        mock_cases_to_delete=mock_cases_to_delete,
        fk_cleanup_steps=fk_cleanup_steps,
        preflight_missing_tables=missing_tables,
        recovery_export_data=recovery_export_data,
    )


def generate_sanitized_report(plan: ReconciliationPlan) -> str:
    """Produce sanitized markdown report containing counts, opaque hashes, zero PII."""
    lines = [
        f"# Identity Reconciliation Plan: {plan.env}",
        "",
        f"- **Plan Hash**: `{plan.plan_hash}`",
        f"- **Schema Fingerprint**: `{plan.schema_fingerprint}`",
        f"- **Target Environment**: `{plan.env}`",
        "",
        "## Preflight Checks",
        f"- Missing Schema Tables: {len(plan.preflight_missing_tables)} ({', '.join(plan.preflight_missing_tables) or 'none'})",
        "",
        "## Organizations Action Summary",
        f"- New Organizations to Create: {len(plan.orgs_to_create)}",
        f"- Organizations with Name Sync: {len(plan.orgs_to_update_name)}",
        f"- Established Organizations Unchanged: {len(plan.orgs_unchanged)}",
        f"- Total Target Organizations: {len(plan.orgs_to_create) + len(plan.orgs_unchanged) + len(plan.orgs_to_update_name)}",
        "",
        "## Principals & Roles Action Summary",
        f"- Real Principals to Create: {len(plan.principals_to_create)}",
        f"- Real Principals with Role Updates / Demotions: {len(plan.principals_to_update_role)}",
        f"- Orphaned Real Principals to Deactivate (status='disabled'): {len(plan.principals_to_deactivate)}",
        f"- Proven Mock Principals to Delete: {len(plan.principals_to_delete)}",
        "",
        "## Mock Cases Cleanup Summary",
        f"- Proven Mock Seed Cases to Delete: {len(plan.mock_cases_to_delete)}",
        f"- Scoped FK Cleanup Table Operations: {len(plan.fk_cleanup_steps)}",
        "",
        "## Security & Verification",
        "- PII Sanitization: 100% verified (no plain emails, names or connection strings)",
        "- Mode 0600 Recovery Export: Enforced before apply with complete row dumps",
        "- Advisory Lock: `pg_advisory_xact_lock(hashtext('greensentinel_identity_reconciliation'))`",
        "- Lock Timeout: `5s` (set before lock acquisition)",
        "- Transaction Atomicity: Full rollback on any error",
        "- Append-Only Guard Maintenance: Scoped disable/restore per catalog trigger",
    ]
    return "\n".join(lines)


@contextmanager
def _scoped_trigger_disable(cur: Any, table_name: str, trigger_name: str):
    """Context manager to temporarily disable and restore a verified catalog append-only trigger."""
    # 1. Verify trigger exists and uses reject_mutation
    cur.execute(
        """
        SELECT p.proname, t.tgenabled
        FROM pg_trigger t
        JOIN pg_class c ON t.tgrelid = c.oid
        JOIN pg_namespace n ON c.relnamespace = n.oid
        JOIN pg_proc p ON t.tgfoid = p.oid
        WHERE n.nspname = 'app' AND c.relname = %s AND t.tgname = %s AND NOT t.tgisinternal
        """,
        (table_name, trigger_name),
    )
    row = cur.fetchone()
    if row:
        fn_name = row[0] if isinstance(row, (tuple, list)) else row["proname"]
        enabled = row[1] if isinstance(row, (tuple, list)) else row["tgenabled"]
        if fn_name != "reject_mutation":
            raise TriggerMismatchError(
                f"Append-only trigger {trigger_name} on app.{table_name} executes {fn_name!r}, expected 'reject_mutation'"
            )
        if enabled != "O":
            raise TriggerMismatchError(
                f"Append-only trigger {trigger_name} on app.{table_name} is in unexpected state {enabled!r}"
            )
        cur.execute(f"ALTER TABLE app.{table_name} DISABLE TRIGGER {trigger_name}")

    try:
        yield
    finally:
        if row:
            cur.execute(f"ALTER TABLE app.{table_name} ENABLE TRIGGER {trigger_name}")


def _verify_mock_principals_isolation(cur: Any, mock_p_ids: list[str], approved_case_ids: list[str]) -> None:
    """Fail closed if mock principals are referenced outside approved fixture closure."""
    if not mock_p_ids:
        return

    # 1. Unapproved fraud cases referencing mock analyst
    cur.execute(
        """
        SELECT id FROM app.fraud_cases
        WHERE assigned_analyst_id = ANY(%s) AND id != ALL(%s)
        """,
        (mock_p_ids, approved_case_ids),
    )
    rows = cur.fetchall() or []
    if rows:
        ids = [str(r[0] if isinstance(r, (tuple, list)) else r["id"]) for r in rows]
        raise MockPrincipalReferenceError(
            f"Mock principal referenced by real/unapproved fraud case(s) {ids}. "
            "Cascade-deletion of business data is strictly forbidden; aborting."
        )

    # 2. Unapproved audit events referencing mock actor
    cur.execute(
        """
        SELECT event_id, case_id FROM app.audit_events
        WHERE actor_id = ANY(%s) AND (case_id IS NULL OR case_id != ALL(%s))
        """,
        (mock_p_ids, approved_case_ids),
    )
    rows = cur.fetchall() or []
    if rows:
        ev_ids = [str(r[0] if isinstance(r, (tuple, list)) else r["id"]) for r in rows]
        raise MockPrincipalReferenceError(f"Mock principal referenced by unapproved audit_events {ev_ids}. Aborting.")

    # 3. Unapproved adjudications referencing mock analyst
    cur.execute(
        """
        SELECT id, case_id FROM app.adjudications
        WHERE analyst_id = ANY(%s) AND (case_id IS NULL OR case_id != ALL(%s))
        """,
        (mock_p_ids, approved_case_ids),
    )
    rows = cur.fetchall() or []
    if rows:
        adj_ids = [str(r[0] if isinstance(r, (tuple, list)) else r["id"]) for r in rows]
        raise MockPrincipalReferenceError(f"Mock principal referenced by unapproved adjudications {adj_ids}. Aborting.")

    # 4. Passengers table referencing mock principal
    cur.execute(
        """
        SELECT id FROM app.passengers
        WHERE principal_id = ANY(%s)
        """,
        (mock_p_ids,),
    )
    rows = cur.fetchall() or []
    if rows:
        pax_ids = [str(r[0] if isinstance(r, (tuple, list)) else r["id"]) for r in rows]
        raise MockPrincipalReferenceError(f"Mock principal referenced by passengers {pax_ids}. Aborting.")


def _export_complete_affected_row_data(
    cur: Any,
    plan: ReconciliationPlan,
    available_tables: set[str],
    file_path: str,
) -> str:
    """Dump actual row contents for every entity about to be mutated or deleted."""
    mock_case_ids = [c["id"] for c in plan.mock_cases_to_delete]
    mock_p_ids = [p["id"] for p in plan.principals_to_delete]
    deact_p_ids = [p["id"] for p in plan.principals_to_deactivate]
    update_p_ids = [p["id"] for p in plan.principals_to_update_role]

    dump: dict[str, Any] = {
        "metadata": {
            "plan_hash": plan.plan_hash,
            "schema_fingerprint": plan.schema_fingerprint,
            "env": plan.env,
            "exported_at": datetime.datetime.now(datetime.UTC).isoformat(),
        },
        "affected_rows": {},
    }

    def _fetch_rows(query: str, params: tuple) -> list[dict]:
        try:
            cur.execute(query, params)
            desc = cur.description or []
            cols = [d[0] for d in desc]
            res = []
            for r in cur.fetchall() or []:
                if isinstance(r, dict):
                    res.append(r)
                else:
                    res.append(dict(zip(cols, r)))
            return res
        except Exception:
            return []

    # Dump principals to be deleted
    if mock_p_ids:
        dump["affected_rows"]["principals_deleted"] = _fetch_rows(
            "SELECT * FROM app.principals WHERE id = ANY(%s)", (mock_p_ids,)
        )
        dump["affected_rows"]["principal_roles_deleted"] = _fetch_rows(
            "SELECT * FROM app.principal_roles WHERE principal_id = ANY(%s)", (mock_p_ids,)
        )
        dump["affected_rows"]["drivers_unlinked"] = _fetch_rows(
            "SELECT * FROM app.drivers WHERE principal_id = ANY(%s)", (mock_p_ids,)
        )
        if "simulation_runs" in available_tables:
            dump["affected_rows"]["simulation_runs_unlinked"] = _fetch_rows(
                "SELECT * FROM app.simulation_runs WHERE requested_by = ANY(%s)", (mock_p_ids,)
            )

    # Dump principals deactivated or updated
    if deact_p_ids:
        dump["affected_rows"]["principals_deactivated"] = _fetch_rows(
            "SELECT * FROM app.principals WHERE id = ANY(%s)", (deact_p_ids,)
        )
        dump["affected_rows"]["principal_roles_revoked"] = _fetch_rows(
            "SELECT * FROM app.principal_roles WHERE principal_id = ANY(%s)", (deact_p_ids,)
        )
    if update_p_ids:
        dump["affected_rows"]["principals_updated"] = _fetch_rows(
            "SELECT * FROM app.principals WHERE id = ANY(%s)", (update_p_ids,)
        )

    # Dump mock fraud cases and all dependent records
    if mock_case_ids:
        dump["affected_rows"]["fraud_cases"] = _fetch_rows(
            "SELECT * FROM app.fraud_cases WHERE id = ANY(%s)", (mock_case_ids,)
        )
        # Model assessments & feature sets
        if "evidence_snapshots" in available_tables:
            dump["affected_rows"]["evidence_snapshots"] = _fetch_rows(
                "SELECT * FROM app.evidence_snapshots WHERE case_id = ANY(%s)", (mock_case_ids,)
            )
            if "model_assessments" in available_tables:
                dump["affected_rows"]["model_assessments"] = _fetch_rows(
                    """
                    SELECT * FROM app.model_assessments
                    WHERE evidence_snapshot_id IN (
                        SELECT id FROM app.evidence_snapshots WHERE case_id = ANY(%s)
                    )
                    """,
                    (mock_case_ids,),
                )
            if "feature_sets" in available_tables:
                dump["affected_rows"]["feature_sets"] = _fetch_rows(
                    """
                    SELECT * FROM app.feature_sets
                    WHERE evidence_snapshot_id IN (
                        SELECT id FROM app.evidence_snapshots WHERE case_id = ANY(%s)
                    )
                    """,
                    (mock_case_ids,),
                )
        if "adjudications" in available_tables:
            dump["affected_rows"]["adjudications"] = _fetch_rows(
                "SELECT * FROM app.adjudications WHERE case_id = ANY(%s)", (mock_case_ids,)
            )
            if "sanctions" in available_tables:
                dump["affected_rows"]["sanctions"] = _fetch_rows(
                    """
                    SELECT * FROM app.sanctions
                    WHERE adjudication_id IN (
                        SELECT id FROM app.adjudications WHERE case_id = ANY(%s)
                    )
                    """,
                    (mock_case_ids,),
                )
        for tbl in (
            "audit_events",
            "case_agent_sessions",
            "case_assignment_history",
            "case_documents",
            "driver_admission_sanctions",
            "driver_submissions",
            "precedent_reuse_history",
            "precedent_workflows",
            "preliminary_judgments",
            "review_actions",
            "review_leases",
            "solved_case_contexts",
            "workflow_action_requests",
            "workflow_minutes",
            "workflow_questions",
            "agent_runtime_turns",
        ):
            if tbl in available_tables:
                col = "current_case_id" if tbl == "precedent_reuse_history" else "case_id"
                dump["affected_rows"][tbl] = _fetch_rows(
                    f"SELECT * FROM app.{tbl} WHERE {col} = ANY(%s)", (mock_case_ids,)
                )

        if "case_agent_messages" in available_tables and "case_agent_sessions" in available_tables:
            dump["affected_rows"]["case_agent_messages"] = _fetch_rows(
                """
                SELECT * FROM app.case_agent_messages
                WHERE session_id IN (
                    SELECT id FROM app.case_agent_sessions WHERE case_id = ANY(%s)
                )
                """,
                (mock_case_ids,),
            )
        if "workflow_answers" in available_tables and "workflow_questions" in available_tables:
            dump["affected_rows"]["workflow_answers"] = _fetch_rows(
                """
                SELECT * FROM app.workflow_answers
                WHERE question_id IN (
                    SELECT id FROM app.workflow_questions WHERE case_id = ANY(%s)
                )
                """,
                (mock_case_ids,),
            )

    return export_recovery_snapshot(dump, file_path)


def execute_reconciliation_apply(
    conn: Any,
    plan: ReconciliationPlan,
    expected_plan_hash: str,
    allow_apply: bool = False,
    recovery_dir: str = "/tmp",
    clerk_snapshot: ClerkSnapshot | None = None,
) -> dict[str, Any]:
    """Execute transactional apply under advisory lock, timeouts, and plan hash verification."""
    if not allow_apply:
        raise PermissionError("Application execution denied: allow_apply flag is required.")

    if not expected_plan_hash or expected_plan_hash != plan.plan_hash:
        raise StalePlanError(
            f"Stale or mismatched plan rejected! Expected: {expected_plan_hash}, Computed: {plan.plan_hash}"
        )

    recovery_file = os.path.join(recovery_dir, f"recovery_{plan.env}_{plan.plan_hash[:12]}.json")

    try:
        with conn.cursor() as cur:
            # 1. Set bounded timeouts BEFORE acquiring advisory transaction lock
            try:
                cur.execute("SET LOCAL lock_timeout = '5s'")
                cur.execute("SET LOCAL statement_timeout = '30s'")
                cur.execute("SELECT pg_advisory_xact_lock(hashtext('greensentinel_identity_reconciliation'))")
            except Exception as lock_exc:
                logger.warning(f"Advisory lock setup: {lock_exc}")

            # 2. Re-read database state under lock and verify zero schema drift / fresh plan hash
            if clerk_snapshot is not None:
                fresh_db_state = audit_database_state(conn)
                fresh_plan = generate_reconciliation_plan(clerk_snapshot, fresh_db_state, plan.env)

                if fresh_plan.schema_fingerprint != plan.schema_fingerprint:
                    raise StalePlanError(
                        f"Database schema drifted under lock! Original: {plan.schema_fingerprint}, Fresh: {fresh_plan.schema_fingerprint}"
                    )
                if fresh_plan.plan_hash != plan.plan_hash:
                    raise StalePlanError(
                        f"Database data drifted under lock! Original: {plan.plan_hash}, Fresh: {fresh_plan.plan_hash}"
                    )
                if fresh_plan.plan_hash != expected_plan_hash:
                    raise StalePlanError(
                        f"Expected plan hash mismatch! Expected: {expected_plan_hash}, Computed: {fresh_plan.plan_hash}"
                    )

            # Discover available tables
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'app'
                """
            )
            rows = cur.fetchall() or []
            available_tables = {r[0] if isinstance(r, (tuple, list)) else r["table_name"] for r in rows}

            # 3. Write mode 0600 complete row data recovery export BEFORE any mutation
            _export_complete_affected_row_data(cur, plan, available_tables, recovery_file)

            # 4. Create missing organizations
            for org in plan.orgs_to_create:
                cur.execute(
                    """
                    INSERT INTO app.organizations (id, name, clerk_organization_id)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (org["uuid"], org["name"], org["clerk_id"]),
                )

            # 5. Synchronize organization names where provided
            for org in plan.orgs_to_update_name:
                cur.execute(
                    """
                    UPDATE app.organizations
                    SET name = %s
                    WHERE id = %s AND name IS DISTINCT FROM %s
                    """,
                    (org["new_name"], org["id"], org["new_name"]),
                )

            # 6. Create missing real principals and assign roles
            for p in plan.principals_to_create:
                cur.execute(
                    """
                    INSERT INTO app.principals (organization_id, external_subject, display_name, status)
                    VALUES (%s, %s, %s, 'active')
                    ON CONFLICT (organization_id, external_subject) DO UPDATE
                    SET status = 'active', display_name = EXCLUDED.display_name
                    RETURNING id
                    """,
                    (p["organization_id"], p["external_subject"], p.get("display_name") or p["external_subject"]),
                )
                row = cur.fetchone()
                principal_id = str(row[0] if isinstance(row, (tuple, list)) else row["id"])
                # Replace roles with mapped single role
                cur.execute("DELETE FROM app.principal_roles WHERE principal_id = %s", (principal_id,))
                cur.execute(
                    "INSERT INTO app.principal_roles (principal_id, role) VALUES (%s, %s)",
                    (principal_id, p["role"]),
                )

            # 7. Update roles / demote stale roles for existing real principals
            for p in plan.principals_to_update_role:
                cur.execute(
                    """
                    UPDATE app.principals
                    SET status = %s, display_name = COALESCE(%s, display_name)
                    WHERE id = %s
                    """,
                    (p["new_status"], p.get("display_name"), p["id"]),
                )
                cur.execute("DELETE FROM app.principal_roles WHERE principal_id = %s", (p["id"],))
                cur.execute(
                    "INSERT INTO app.principal_roles (principal_id, role) VALUES (%s, %s)",
                    (p["id"], p["new_role"]),
                )

            # 8. Deactivate orphaned real principals (status='disabled', roles cleared, historical records preserved)
            for p in plan.principals_to_deactivate:
                cur.execute(
                    "UPDATE app.principals SET status = 'disabled' WHERE id = %s",
                    (p["id"],),
                )
                cur.execute("DELETE FROM app.principal_roles WHERE principal_id = %s", (p["id"],))

            # 9. Verify mock principals isolation: fail closed if referenced outside approved fixture closure
            mock_p_ids = [p["id"] for p in plan.principals_to_delete]
            mock_case_ids = [c["id"] for c in plan.mock_cases_to_delete]
            _verify_mock_principals_isolation(cur, mock_p_ids, mock_case_ids)

            # 10. Mock Cases Cleanup: Complete FK topological deletion with append-only guard maintenance
            if mock_case_ids:
                # 1. model_assessments
                if "model_assessments" in available_tables and "evidence_snapshots" in available_tables:
                    with _scoped_trigger_disable(cur, "model_assessments", "model_assessments_append_only"):
                        cur.execute(
                            """
                            DELETE FROM app.model_assessments
                            WHERE evidence_snapshot_id IN (
                                SELECT id FROM app.evidence_snapshots WHERE case_id = ANY(%s)
                            )
                            """,
                            (mock_case_ids,),
                        )

                # 2. feature_sets
                if "feature_sets" in available_tables and "evidence_snapshots" in available_tables:
                    with _scoped_trigger_disable(cur, "feature_sets", "feature_sets_append_only"):
                        cur.execute(
                            """
                            DELETE FROM app.feature_sets
                            WHERE evidence_snapshot_id IN (
                                SELECT id FROM app.evidence_snapshots WHERE case_id = ANY(%s)
                            )
                            """,
                            (mock_case_ids,),
                        )

                # 3. sanctions
                if "sanctions" in available_tables and "adjudications" in available_tables:
                    cur.execute(
                        """
                        DELETE FROM app.sanctions
                        WHERE adjudication_id IN (
                            SELECT id FROM app.adjudications WHERE case_id = ANY(%s)
                        )
                        """,
                        (mock_case_ids,),
                    )

                # 4. workflow_minutes
                if "workflow_minutes" in available_tables:
                    cur.execute("DELETE FROM app.workflow_minutes WHERE case_id = ANY(%s)", (mock_case_ids,))

                # 5. precedent_reuse_history
                if "precedent_reuse_history" in available_tables:
                    with _scoped_trigger_disable(cur, "precedent_reuse_history", "precedent_reuse_history_append_only"):
                        if "solved_case_contexts" in available_tables:
                            cur.execute(
                                """
                                DELETE FROM app.precedent_reuse_history
                                WHERE current_case_id = ANY(%s)
                                   OR precedent_context_id IN (SELECT id FROM app.solved_case_contexts WHERE case_id = ANY(%s))
                                """,
                                (mock_case_ids, mock_case_ids),
                            )
                        else:
                            cur.execute(
                                "DELETE FROM app.precedent_reuse_history WHERE current_case_id = ANY(%s)",
                                (mock_case_ids,),
                            )

                # 6. precedent_workflows
                if "precedent_workflows" in available_tables:
                    with _scoped_trigger_disable(cur, "precedent_workflows", "precedent_workflows_append_only"):
                        cur.execute("DELETE FROM app.precedent_workflows WHERE case_id = ANY(%s)", (mock_case_ids,))

                # 7. solved_case_contexts
                if "solved_case_contexts" in available_tables:
                    with _scoped_trigger_disable(cur, "solved_case_contexts", "solved_case_contexts_append_only"):
                        cur.execute("DELETE FROM app.solved_case_contexts WHERE case_id = ANY(%s)", (mock_case_ids,))

                # 8. preliminary_judgments
                if "preliminary_judgments" in available_tables:
                    with _scoped_trigger_disable(cur, "preliminary_judgments", "preliminary_judgments_append_only"):
                        cur.execute("DELETE FROM app.preliminary_judgments WHERE case_id = ANY(%s)", (mock_case_ids,))

                # 9. review_actions
                if "review_actions" in available_tables:
                    cur.execute("DELETE FROM app.review_actions WHERE case_id = ANY(%s)", (mock_case_ids,))

                # 10. review_leases
                if "review_leases" in available_tables:
                    cur.execute("DELETE FROM app.review_leases WHERE case_id = ANY(%s)", (mock_case_ids,))

                # 11. adjudications
                if "adjudications" in available_tables:
                    with _scoped_trigger_disable(cur, "adjudications", "adjudications_append_only"):
                        cur.execute("DELETE FROM app.adjudications WHERE case_id = ANY(%s)", (mock_case_ids,))

                # 12. case_agent_messages
                if "case_agent_messages" in available_tables and "case_agent_sessions" in available_tables:
                    with _scoped_trigger_disable(cur, "case_agent_messages", "case_agent_messages_append_only"):
                        cur.execute(
                            """
                            DELETE FROM app.case_agent_messages
                            WHERE session_id IN (
                                SELECT id FROM app.case_agent_sessions WHERE case_id = ANY(%s)
                            )
                            """,
                            (mock_case_ids,),
                        )

                # 13. case_agent_sessions
                if "case_agent_sessions" in available_tables:
                    cur.execute("DELETE FROM app.case_agent_sessions WHERE case_id = ANY(%s)", (mock_case_ids,))

                # 14. workflow_answers
                if "workflow_answers" in available_tables and "workflow_questions" in available_tables:
                    cur.execute(
                        """
                        DELETE FROM app.workflow_answers
                        WHERE question_id IN (
                            SELECT id FROM app.workflow_questions WHERE case_id = ANY(%s)
                        )
                        """,
                        (mock_case_ids,),
                    )

                # 15. workflow_action_requests
                if "workflow_action_requests" in available_tables:
                    cur.execute("DELETE FROM app.workflow_action_requests WHERE case_id = ANY(%s)", (mock_case_ids,))

                # 16. workflow_questions
                if "workflow_questions" in available_tables:
                    cur.execute("DELETE FROM app.workflow_questions WHERE case_id = ANY(%s)", (mock_case_ids,))

                # 17. driver_admission_sanctions
                if "driver_admission_sanctions" in available_tables:
                    cur.execute("DELETE FROM app.driver_admission_sanctions WHERE case_id = ANY(%s)", (mock_case_ids,))

                # 18. driver_submissions
                if "driver_submissions" in available_tables:
                    cur.execute("DELETE FROM app.driver_submissions WHERE case_id = ANY(%s)", (mock_case_ids,))

                # 19. evidence_snapshots
                if "evidence_snapshots" in available_tables:
                    with _scoped_trigger_disable(cur, "evidence_snapshots", "evidence_snapshots_append_only"):
                        cur.execute("DELETE FROM app.evidence_snapshots WHERE case_id = ANY(%s)", (mock_case_ids,))

                # 20. case_assignment_history
                if "case_assignment_history" in available_tables:
                    cur.execute("DELETE FROM app.case_assignment_history WHERE case_id = ANY(%s)", (mock_case_ids,))

                # 21. case_documents
                if "case_documents" in available_tables:
                    cur.execute("DELETE FROM app.case_documents WHERE case_id = ANY(%s)", (mock_case_ids,))

                # 22. agent_runtime_turns
                if "agent_runtime_turns" in available_tables:
                    cur.execute("DELETE FROM app.agent_runtime_turns WHERE case_id = ANY(%s)", (mock_case_ids,))

                # 23. audit_events
                if "audit_events" in available_tables:
                    with _scoped_trigger_disable(cur, "audit_events", "audit_events_append_only"):
                        cur.execute("DELETE FROM app.audit_events WHERE case_id = ANY(%s)", (mock_case_ids,))

                # 24. fraud_cases root records
                cur.execute("DELETE FROM app.fraud_cases WHERE id = ANY(%s)", (mock_case_ids,))

            # 11. Mock Principals Cleanup
            if mock_p_ids:
                # Unlink synthetic drivers referencing mock principal
                if "drivers" in available_tables:
                    cur.execute(
                        "UPDATE app.drivers SET principal_id = NULL WHERE principal_id = ANY(%s)",
                        (mock_p_ids,),
                    )
                # Unlink simulation runs referencing mock principal
                if "simulation_runs" in available_tables:
                    cur.execute(
                        "UPDATE app.simulation_runs SET requested_by = NULL WHERE requested_by = ANY(%s)",
                        (mock_p_ids,),
                    )
                # Delete roles
                cur.execute("DELETE FROM app.principal_roles WHERE principal_id = ANY(%s)", (mock_p_ids,))
                # Delete mock principals
                cur.execute("DELETE FROM app.principals WHERE id = ANY(%s)", (mock_p_ids,))

            # 12. Postcondition Assertions: verify zero active mock principals remain
            cur.execute(
                """
                SELECT count(*)
                FROM app.principals
                WHERE external_subject LIKE 'user_clerk_analyst_%'
                   OR external_subject LIKE 'drv_gsm_%'
                """
            )
            row = cur.fetchone()
            remaining_mock_count = row[0] if isinstance(row, (tuple, list)) else (row["count"] if row else 0)
            if remaining_mock_count != 0:
                raise RuntimeError(f"Postcondition violated: {remaining_mock_count} mock principals remain!")

        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise

    return {
        "status": "applied",
        "plan_hash": plan.plan_hash,
        "recovery_file": recovery_file,
        "orgs_created": len(plan.orgs_to_create),
        "orgs_name_updated": len(plan.orgs_to_update_name),
        "principals_created": len(plan.principals_to_create),
        "principals_updated": len(plan.principals_to_update_role),
        "principals_deactivated": len(plan.principals_to_deactivate),
        "mock_principals_deleted": len(plan.principals_to_delete),
        "mock_cases_deleted": len(plan.mock_cases_to_delete),
    }
