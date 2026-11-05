"""Persisted authorization records. HTTP adapters never provision identity grants."""

from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid5

from fastapi import HTTPException


def _require_real_organization_id(organization_id: str | None) -> str:
    """Reject missing or Clerk-native org ids. Never fall back to a default org."""
    if not organization_id:
        raise HTTPException(403, "Clerk organization membership required")
    if organization_id.startswith("org_"):
        raise HTTPException(403, "Clerk organization is not provisioned")
    try:
        UUID(str(organization_id))
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(403, "Clerk organization membership required") from exc
    return str(organization_id)


def resolve_clerk_organization_id(connection_factory: Callable[[], Any], clerk_organization_id: str) -> str | None:
    """Map an explicitly linked native Clerk org id to its provisioned UUID.

    Links are admin-provisioned out-of-band (app.organizations.clerk_organization_id);
    unlinked native orgs return None so callers keep denying them. Never synthesizes a mapping.
    """
    conn = None
    try:
        conn = connection_factory()
        if conn is None:
            raise HTTPException(503, "Principal database unavailable")
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM app.organizations WHERE clerk_organization_id = %s",
                (clerk_organization_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return str(row["id"] if isinstance(row, dict) else row[0])
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "Principal database unavailable") from exc
    finally:
        if conn is not None:
            conn.close()


def bootstrap_clerk_organization(
    connection_factory: Callable[[], Any],
    clerk_organization_id: str,
    name: str | None,
    subject: str,
    display_name: str | None = None,
) -> dict[str, str]:
    """Create a tenant for a native Clerk org and provision its creator as admin.

    Self-serve path for org creators only: callers must verify org_role == org:admin
    first. A Clerk org admin owns that org, so minting a fresh empty tenant grants
    nothing outside it. Members (non-admin) of unlinked orgs stay denied. Idempotent
    per clerk_organization_id: concurrent creators converge on one tenant.
    """
    org_name = (name or "").strip() or f"Organization {clerk_organization_id[-6:]}"
    effective_name = (display_name or "").strip() or subject
    conn = None
    try:
        conn = connection_factory()
        if conn is None:
            raise HTTPException(503, "Principal database unavailable")
        with conn.cursor() as cursor:
            try:
                cursor.execute(
                    """
                    INSERT INTO app.organizations (name, clerk_organization_id)
                    VALUES (%s, %s)
                    ON CONFLICT (clerk_organization_id) DO NOTHING
                    RETURNING id
                    """,
                    (org_name, clerk_organization_id),
                )
                row = cursor.fetchone()
                if row is None:
                    cursor.execute(
                        "SELECT id FROM app.organizations WHERE clerk_organization_id = %s",
                        (clerk_organization_id,),
                    )
                    row = cursor.fetchone()
                org_id = str(row["id"] if isinstance(row, dict) else row[0])
                cursor.execute(
                    """
                    INSERT INTO app.principals (organization_id, external_subject, display_name, status)
                    VALUES (%s, %s, %s, 'active')
                    ON CONFLICT (organization_id, external_subject)
                    DO UPDATE SET status = 'active', display_name = EXCLUDED.display_name
                    RETURNING id
                    """,
                    (org_id, subject, effective_name),
                )
                principal_row = cursor.fetchone()
                principal_id = str(principal_row["id"] if isinstance(principal_row, dict) else principal_row[0])
                cursor.execute(
                    """
                    INSERT INTO app.principal_roles (principal_id, role)
                    VALUES (%s, %s)
                    ON CONFLICT (principal_id, role) DO NOTHING
                    """,
                    (principal_id, "admin"),
                )
            except HTTPException:
                raise
            except Exception:
                if hasattr(conn, "rollback"):
                    conn.rollback()
                raise HTTPException(503, "Principal database unavailable")
            if hasattr(conn, "commit"):
                conn.commit()
            return {"organization_id": org_id, "principal_id": principal_id}
    except HTTPException:
        raise
    except Exception as exc:
        if conn is not None and hasattr(conn, "rollback"):
            conn.rollback()
        raise HTTPException(503, "Principal database unavailable") from exc
    finally:
        if conn is not None:
            conn.close()


def load_principal(
    connection_factory: Callable[[], Any], subject: str, organization_id: str | None = None
) -> dict[str, Any] | None:
    """Load one unambiguous subject; database roles/status remain authoritative."""
    conn = None
    try:
        conn = connection_factory()
        if conn is None:
            raise HTTPException(503, "Principal database unavailable")
        with conn.cursor() as cursor:
            query = """
                SELECT p.id, p.organization_id, p.status, array_remove(array_agg(r.role), null) AS roles,
                       (SELECT d.id FROM app.drivers d WHERE d.principal_id = p.id
                        AND d.organization_id = p.organization_id LIMIT 1) AS driver_id
                FROM app.principals p
                LEFT JOIN app.principal_roles r ON r.principal_id = p.id
                WHERE p.external_subject = %s
            """
            params: tuple[str, ...] = (subject,)
            if organization_id:
                query += " AND p.organization_id = %s"
                params += (organization_id,)
            cursor.execute(
                query
                + """
                GROUP BY p.id, p.organization_id LIMIT 2
                """,
                params,
            )
            first = cursor.fetchone()
            if first is None:
                return None
            # A subject must never select an arbitrary tenant when legacy data
            # contains duplicate rows. Require an explicit administrative fix.
            second = cursor.fetchone()
            if second is not None:
                raise HTTPException(403, "Clerk identity has ambiguous organization assignments")
            if isinstance(first, dict):
                return first
            return {
                "id": str(first[0]),
                "organization_id": str(first[1]),
                "status": first[2],
                "roles": list(first[3] or []),
                "driver_id": str(first[4]) if first[4] else None,
            }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "Principal database unavailable") from exc
    finally:
        if conn is not None:
            conn.close()


def _ensure_driver_profile_tx(
    cursor: Any,
    principal_id: str,
    effective_org_id: str | UUID,
    subject: str,
    display_name: str | None = None,
) -> str:
    """Ensure a driver profile exists under an active transaction cursor without touching principal or roles."""
    # 1. Preserve existing valid explicit driver link for this principal
    cursor.execute(
        """
        SELECT id, organization_id, external_ref
        FROM app.drivers
        WHERE principal_id = %s
        LIMIT 2
        """,
        (principal_id,),
    )
    existing_driver_rows = cursor.fetchall()
    if len(existing_driver_rows) > 1:
        raise HTTPException(409, "Multiple driver profiles linked to principal")
    if existing_driver_rows:
        drow = existing_driver_rows[0]
        existing_org = str(drow["organization_id"] if isinstance(drow, dict) else drow[1])
        if existing_org != str(effective_org_id):
            raise HTTPException(403, "Driver organization mismatch")
        return str(drow["id"] if isinstance(drow, dict) else drow[0])

    # 2. Deterministic real driver profile creation: UUID5(org, subject)
    try:
        org_uuid = UUID(str(effective_org_id))
    except (ValueError, TypeError) as exc:
        raise HTTPException(403, "Invalid organization UUID") from exc

    deterministic_driver_id = str(uuid5(org_uuid, subject))
    ext_ref = f"clerk:{subject}"
    effective_name = display_name or subject

    # Enforce collision fail-closed check
    cursor.execute(
        """
        SELECT id, organization_id, principal_id
        FROM app.drivers
        WHERE id = %s OR (organization_id = %s AND external_ref = %s)
        LIMIT 2
        """,
        (deterministic_driver_id, str(effective_org_id), ext_ref),
    )
    collision_rows = cursor.fetchall()
    if collision_rows:
        for crow in collision_rows:
            crow_pid = crow["principal_id"] if isinstance(crow, dict) else crow[2]
            crow_org = str(crow["organization_id"] if isinstance(crow, dict) else crow[1])
            crow_id = str(crow["id"] if isinstance(crow, dict) else crow[0])
            if crow_pid == principal_id and crow_org == str(effective_org_id):
                return crow_id
            raise HTTPException(409, "Driver profile collision")

    cursor.execute(
        """
        INSERT INTO app.drivers (
            id,
            organization_id,
            principal_id,
            external_ref,
            display_name,
            partner_type,
            account_status,
            is_synthetic
        )
        VALUES (%s, %s, %s, %s, %s, 'owner_driver', 'active', false)
        ON CONFLICT (id) DO NOTHING
        RETURNING id
        """,
        (
            deterministic_driver_id,
            str(effective_org_id),
            principal_id,
            ext_ref,
            effective_name,
        ),
    )
    inserted = cursor.fetchone()
    if inserted:
        return str(inserted["id"] if isinstance(inserted, dict) else inserted[0])

    cursor.execute(
        "SELECT id, organization_id, principal_id FROM app.drivers WHERE id = %s",
        (deterministic_driver_id,),
    )
    existing_row = cursor.fetchone()
    if existing_row:
        ex_pid = existing_row["principal_id"] if isinstance(existing_row, dict) else existing_row[2]
        ex_org = str(existing_row["organization_id"] if isinstance(existing_row, dict) else existing_row[1])
        if ex_pid == principal_id and ex_org == str(effective_org_id):
            return str(existing_row["id"] if isinstance(existing_row, dict) else existing_row[0])
        raise HTTPException(409, "Driver profile collision")
    raise HTTPException(503, "Failed to provision driver profile")


def ensure_driver_profile(
    connection_factory: Callable[[], Any],
    principal_id: str,
    organization_id: str,
    subject: str,
    display_name: str | None = None,
) -> str:
    """Ensure driver profile exists in app.drivers for an existing principal.

    Never touches app.principals or app.principal_roles.
    Preserves existing valid driver links, derives deterministic UUID5(org, subject)
    for new profiles, and fails closed on collision (409) or db error (503).
    """
    effective_org_id = _require_real_organization_id(organization_id)
    conn = None
    try:
        conn = connection_factory()
        if conn is None:
            raise HTTPException(503, "Principal database unavailable")
        with conn.cursor() as cursor:
            driver_id = _ensure_driver_profile_tx(
                cursor,
                principal_id=principal_id,
                effective_org_id=effective_org_id,
                subject=subject,
                display_name=display_name,
            )
            if hasattr(conn, "commit"):
                conn.commit()
            return driver_id
    except HTTPException:
        if conn is not None and hasattr(conn, "rollback"):
            conn.rollback()
        raise
    except Exception as exc:
        if conn is not None and hasattr(conn, "rollback"):
            conn.rollback()
        sqlstate = getattr(exc, "sqlstate", None) or getattr(getattr(exc, "diag", None), "sqlstate", None)
        if sqlstate == "23505" or "unique constraint" in str(exc).lower() or "UniqueViolation" in type(exc).__name__:
            raise HTTPException(409, "Driver profile collision") from exc
        raise HTTPException(503, "Principal database unavailable") from exc
    finally:
        if conn is not None and hasattr(conn, "close"):
            conn.close()


def sync_clerk_principal(
    connection_factory: Callable[[], Any],
    subject: str,
    organization_id: str | None = None,
    role: str | None = None,
    display_name: str | None = None,
) -> dict[str, Any] | None:
    """Sync Clerk user to app.principals and app.principal_roles (JIT provisioning).

    Requires a real provisioned organization_id (UUID) and an explicit role.
    Never falls back to a default org or a default role. Callers must only
    invoke this when the Clerk session carries an org_role or the subject
    already has a DB row; otherwise deny with 403 upstream.
    """
    effective_org_id = _require_real_organization_id(organization_id)
    if not role:
        raise HTTPException(403, "Clerk user has no active assigned role")
    conn = None
    try:
        conn = connection_factory()
        if conn is None:
            raise HTTPException(503, "Principal database unavailable")

        effective_name = display_name or subject

        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO app.principals (organization_id, external_subject, display_name, status)
                VALUES (%s, %s, %s, 'active')
                ON CONFLICT (organization_id, external_subject)
                DO UPDATE SET status = 'active', display_name = EXCLUDED.display_name
                RETURNING id, organization_id
                """,
                (effective_org_id, subject, effective_name),
            )
            row = cursor.fetchone()
            principal_id = row["id"] if row else subject
            effective_org_id = row.get("organization_id", effective_org_id) if row else effective_org_id

            cursor.execute(
                """
                INSERT INTO app.principal_roles (principal_id, role)
                VALUES (%s, %s)
                ON CONFLICT (principal_id, role) DO NOTHING
                """,
                (principal_id, role),
            )

            driver_id = None
            if role == "driver":
                driver_id = _ensure_driver_profile_tx(
                    cursor,
                    principal_id=principal_id,
                    effective_org_id=effective_org_id,
                    subject=subject,
                    display_name=effective_name,
                )

            if hasattr(conn, "commit"):
                conn.commit()

            return {
                "id": str(principal_id),
                "organization_id": str(effective_org_id),
                "roles": [role],
                "driver_id": driver_id,
            }
    except HTTPException:
        if conn is not None and hasattr(conn, "rollback"):
            conn.rollback()
        raise
    except Exception as exc:
        if conn is not None and hasattr(conn, "rollback"):
            conn.rollback()
        sqlstate = getattr(exc, "sqlstate", None) or getattr(getattr(exc, "diag", None), "sqlstate", None)
        if sqlstate == "23505" or "unique constraint" in str(exc).lower() or "UniqueViolation" in type(exc).__name__:
            raise HTTPException(409, "Driver profile collision") from exc
        raise HTTPException(503, "Principal database unavailable") from exc
    finally:
        if conn is not None and hasattr(conn, "close"):
            conn.close()


def require_case_scope(
    service: Any,
    case_id: str,
    organization_id: str,
    driver_id: str | None = None,
    *,
    anti_probing_driver_mismatch: bool = False,
) -> None:
    """Authorize before emitting history, attachments, stream headers, or mutating a case.

    `anti_probing_driver_mismatch`: for driver-self-service endpoints (chat,
    chat-stream, session) that must never let a non-owner distinguish
    "case exists but isn't mine" from "case doesn't exist", a driver
    ownership mismatch on the in-memory (no-DB, test-only) fallback path
    raises 404 instead of 403 (Issue #157). Every other caller/path keeps
    the plain 403 "Driver is not assigned to this case" contract (Issue
    #572; test_agent_session_isolation.py,
    test_driver_escalation_transitions.py). The real-DB path is never
    affected by this flag: production authorization is unchanged either way.
    """
    conn = service._get_db_connection()
    if conn is None:
        if service.settings.app_env == "test" and service.settings.test_auth_enabled:
            case = service._cases.get(service._resolve_case_id(case_id), {})
            if case.get("organization_id", organization_id) != organization_id:
                raise HTTPException(403, "Case access denied")
            if driver_id is not None and driver_id != "driver-guest":
                asgn = getattr(service, "_assignments", {}).get(case.get("assignment_id"), {})
                case_driver = case.get("driver_id") or asgn.get("driver_id")
                if case_driver and str(case_driver) != driver_id:
                    if anti_probing_driver_mismatch:
                        raise HTTPException(404, f"Case {case_id} not found")
                    raise HTTPException(403, "Driver is not assigned to this case")
            return
        raise HTTPException(503, "Authorization database unavailable")
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT c.organization_id, a.driver_id
                FROM app.fraud_cases c LEFT JOIN app.trip_assignments a ON a.id = c.assignment_id
                WHERE c.id::text = %s""",
                (case_id,),
            )
            row = cursor.fetchone()
        if not row:
            settings = getattr(service, "settings", None)
            cases = getattr(service, "_cases", None)
            if (
                settings
                and getattr(settings, "app_env", "") == "test"
                and getattr(settings, "test_auth_enabled", False)
                and cases is not None
            ):
                resolve_fn = getattr(service, "_resolve_case_id", None)
                cid = resolve_fn(case_id) if callable(resolve_fn) else case_id
                case = cases.get(cid)
                if not case:
                    for k, c in cases.items():
                        if k == case_id or str(c.get("id")) == case_id:
                            case = c
                            break
                if case:
                    if case.get("organization_id", organization_id) != organization_id:
                        raise HTTPException(403, "Case access denied")
                    if driver_id is not None and driver_id != "driver-guest":
                        asgn_id = case.get("assignment_id")
                        assignments = getattr(service, "_assignments", {})
                        asgn = assignments.get(str(asgn_id)) if asgn_id else {}
                        case_driver_id = str(asgn.get("driver_id", "")) if asgn else str(case.get("driver_id", ""))
                        if case_driver_id and case_driver_id != driver_id:
                            raise HTTPException(403, "Driver is not assigned to this case")
                    return
            raise HTTPException(403, "Case access denied")
        if str(row["organization_id"]) != organization_id:
            raise HTTPException(403, "Case access denied")
        if driver_id is not None and driver_id != "driver-guest" and str(row.get("driver_id")) != driver_id:
            raise HTTPException(403, "Driver is not assigned to this case")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "Authorization database unavailable") from exc
    finally:
        conn.close()
