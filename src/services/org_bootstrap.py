"""S4-ACTORS #295: idempotent per-organization actor bootstrap (ADR-025 §4).

Creates exactly 100 drivers + 1000 customers (passengers) per organization.

Contract guarantees:
- Deterministic org-specific IDs (uuid5 over org + seed + template + index),
  so retries and concurrent bootstraps converge on the same rows.
- Idempotent inserts: ``ON CONFLICT DO NOTHING`` + unique
  ``(organization_id, external_ref)`` constraints → reruns add zero dupes.
- Resumable: batched commits with progress in ``app.org_bootstrap_state``;
  a crash leaves ``status='running'`` and the next run resumes to ``ready``.
- Lineage recorded per row (``profile_provenance``) and per run
  (``app.org_bootstrap_state.detail``); mutable activity, ratings, trips and
  cases are never copied or created here.
- Seeded entities are NOT Clerk accounts: ``principal_id`` stays NULL until
  an explicit Admin driver-link (``link_driver_principal``), which enforces
  same-org on both sides (DB trigger ``driver_principal_org_match`` backs it).
- Readiness is verified, never claimed: ``ready`` is set only after exact
  100/1000 counts are observed; an unavailable/partial bootstrap reports
  ``running``/``unavailable``.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

DRIVER_COUNT = 100
CUSTOMER_COUNT = 1000
BATCH_SIZE = 100

DEFAULT_TEMPLATE_VERSION = "v1"
DEFAULT_SEED = "p063-s4-actors"

_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class BootstrapError(RuntimeError):
    """Base error for org bootstrap failures."""


class DatabaseUnavailableError(BootstrapError):
    """No usable database connection; caller should retry later."""


class NotFoundError(BootstrapError):
    """Referenced driver or principal row does not exist."""


class OrgMismatchError(BootstrapError):
    """Cross-org bind attempt; denied before any write."""


def _check_uuid(value: str, field: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError) as exc:
        raise BootstrapError(f"Invalid {field}: {value!r} is not a UUID") from exc


def _check_label(value: str, field: str) -> str:
    if not _LABEL_RE.match(str(value)):
        raise BootstrapError(f"Invalid {field}: {value!r}")
    return str(value)


def driver_id_for(organization_id: str, index: int, *, seed: str, template_version: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{organization_id}:{seed}:{template_version}:driver:{index}"))


def customer_id_for(organization_id: str, index: int, *, seed: str, template_version: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{organization_id}:{seed}:{template_version}:customer:{index}"))


def driver_external_ref(*, seed: str, template_version: str, index: int) -> str:
    return f"s4-{seed}-drv-{template_version}-{index:04d}"


def customer_external_ref(*, seed: str, template_version: str, index: int) -> str:
    return f"s4-{seed}-cus-{template_version}-{index:04d}"


def lineage_payload(*, template_version: str, seed: str) -> dict[str, Any]:
    return {"template_version": template_version, "seed": seed, "generator": "org_bootstrap"}


def _open_conn(db_conn_factory: Callable[[], Any]) -> Any:
    try:
        conn = db_conn_factory() if callable(db_conn_factory) else db_conn_factory
    except Exception as exc:
        raise DatabaseUnavailableError(f"Bootstrap database unavailable: {exc}") from exc
    if conn is None:
        raise DatabaseUnavailableError("Bootstrap database unavailable (no connection)")
    return conn


def get_bootstrap_status(
    organization_id: str,
    db_conn_factory: Callable[[], Any],
    template_version: str = DEFAULT_TEMPLATE_VERSION,
    seed: str = DEFAULT_SEED,
) -> dict[str, Any]:
    """Read bootstrap state; never claims readiness without exact counts."""
    org = _check_uuid(organization_id, "organization_id")
    template_version = _check_label(template_version, "template_version")
    seed = _check_label(seed, "seed")
    conn = _open_conn(db_conn_factory)
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute(
                "SELECT status, drivers_created, customers_created, detail"
                " FROM app.org_bootstrap_state"
                " WHERE organization_id = %s AND template_version = %s AND seed = %s;",
                (org, template_version, seed),
            )
            row = cur.fetchone()
            if row is None:
                return {
                    "organization_id": org,
                    "template_version": template_version,
                    "seed": seed,
                    "status": "unavailable",
                    "ready": False,
                    "drivers": 0,
                    "customers": 0,
                }
            status = row["status"] if isinstance(row, dict) else row[0]
            ready = status == "ready"
            return {
                "organization_id": org,
                "template_version": template_version,
                "seed": seed,
                "status": status,
                "ready": ready,
                "drivers": (row["drivers_created"] if isinstance(row, dict) else row[1]) or 0,
                "customers": (row["customers_created"] if isinstance(row, dict) else row[2]) or 0,
            }
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _count_seeded(cur: Any, table: str, org: str, prefix: str) -> int:
    cur.execute(
        f"SELECT COUNT(*) AS count FROM app.{table} WHERE organization_id = %s AND external_ref LIKE %s;",
        (org, prefix + "%"),
    )
    row = cur.fetchone()
    if row is None:
        return 0
    if isinstance(row, dict):
        return int(row.get("count", 0))
    return int(row[0])


def bootstrap_org_population(
    organization_id: str,
    db_conn_factory: Callable[[], Any],
    template_version: str = DEFAULT_TEMPLATE_VERSION,
    seed: str = DEFAULT_SEED,
) -> dict[str, Any]:
    """Idempotently create exactly 100 drivers + 1000 customers for one org.

    Safe under retries, concurrent bootstrap, and crash-resume: deterministic
    IDs + ``ON CONFLICT DO NOTHING`` converge; progress persists per batch.
    """
    org = _check_uuid(organization_id, "organization_id")
    template_version = _check_label(template_version, "template_version")
    seed = _check_label(seed, "seed")
    conn = _open_conn(db_conn_factory)
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            # Claim/resume the run. Concurrent bootstraps converge: the row is
            # created once, every runner then inserts the same deterministic set.
            cur.execute(
                "INSERT INTO app.org_bootstrap_state"
                " (organization_id, template_version, seed, status,"
                " drivers_created, customers_created, detail)"
                " VALUES (%s, %s, %s, 'running', 0, 0, %s)"
                " ON CONFLICT DO NOTHING;",
                (
                    org,
                    template_version,
                    seed,
                    json.dumps(lineage_payload(template_version=template_version, seed=seed)),
                ),
            )
            conn.commit()

            drv_prefix = f"s4-{seed}-drv-{template_version}-"
            cus_prefix = f"s4-{seed}-cus-{template_version}-"

            for start in range(0, DRIVER_COUNT, BATCH_SIZE):
                rows = [
                    (
                        driver_id_for(org, i, seed=seed, template_version=template_version),
                        org,
                        driver_external_ref(seed=seed, template_version=template_version, index=i),
                        f"Seed Driver {i:03d}",
                        json.dumps(lineage_payload(template_version=template_version, seed=seed)),
                    )
                    for i in range(start, min(start + BATCH_SIZE, DRIVER_COUNT))
                ]
                cur.executemany(
                    "INSERT INTO app.drivers"
                    " (id, organization_id, external_ref, display_name,"
                    " partner_type, account_status, is_synthetic, profile_provenance)"
                    " VALUES (%s, %s, %s, %s, 'fleet', 'active', true, %s)"
                    " ON CONFLICT DO NOTHING;",
                    rows,
                )
                conn.commit()

            for start in range(0, CUSTOMER_COUNT, BATCH_SIZE):
                rows = [
                    (
                        customer_id_for(org, i, seed=seed, template_version=template_version),
                        org,
                        customer_external_ref(seed=seed, template_version=template_version, index=i),
                        f"Seed Customer {i:04d}",
                        json.dumps(lineage_payload(template_version=template_version, seed=seed)),
                    )
                    for i in range(start, min(start + BATCH_SIZE, CUSTOMER_COUNT))
                ]
                cur.executemany(
                    "INSERT INTO app.passengers"
                    " (id, organization_id, external_ref, display_name, is_synthetic, profile_provenance)"
                    " VALUES (%s, %s, %s, %s, true, %s)"
                    " ON CONFLICT DO NOTHING;",
                    rows,
                )
                conn.commit()

            drivers = _count_seeded(cur, "drivers", org, drv_prefix)
            customers = _count_seeded(cur, "passengers", org, cus_prefix)
            status = "ready" if (drivers == DRIVER_COUNT and customers == CUSTOMER_COUNT) else "running"
            cur.execute(
                "UPDATE app.org_bootstrap_state"
                " SET status = %s, drivers_created = %s, customers_created = %s,"
                " detail = %s, updated_at = now()"
                " WHERE organization_id = %s AND template_version = %s AND seed = %s;",
                (
                    status,
                    drivers,
                    customers,
                    json.dumps(
                        {
                            **lineage_payload(template_version=template_version, seed=seed),
                            "drivers": drivers,
                            "customers": customers,
                        }
                    ),
                    org,
                    template_version,
                    seed,
                ),
            )
            conn.commit()
            logger.info(
                "org bootstrap org=%s seed=%s tv=%s drivers=%d customers=%d status=%s",
                org,
                seed,
                template_version,
                drivers,
                customers,
                status,
            )
            return {
                "organization_id": org,
                "template_version": template_version,
                "seed": seed,
                "drivers": drivers,
                "customers": customers,
                "status": status,
                "ready": status == "ready",
            }
    except DatabaseUnavailableError:
        raise
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        raise BootstrapError(f"Bootstrap failed for org {organization_id}: {exc}") from exc
    finally:
        try:
            conn.close()
        except Exception:
            pass


def link_driver_principal(
    driver_id: str,
    principal_id: str,
    organization_id: str,
    db_conn_factory: Callable[[], Any],
) -> dict[str, Any]:
    """Explicit Admin bind of a Driver member to an owned driver entity.

    Both rows must belong to ``organization_id``; cross-org binds are denied
    before any write (the ``driver_principal_org_match`` trigger backs this).
    """
    driver_id = _check_uuid(driver_id, "driver_id")
    principal_id = _check_uuid(principal_id, "principal_id")
    org = _check_uuid(organization_id, "organization_id")
    conn = _open_conn(db_conn_factory)
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute("SELECT id, organization_id FROM app.drivers WHERE id = %s;", (driver_id,))
            driver = cur.fetchone()
            if driver is None:
                raise NotFoundError(f"Driver {driver_id} not found")
            driver_org = driver["organization_id"] if isinstance(driver, dict) else driver[1]
            if str(driver_org) != org:
                raise OrgMismatchError("Driver belongs to another organization")
            cur.execute("SELECT id, organization_id FROM app.principals WHERE id = %s;", (principal_id,))
            principal = cur.fetchone()
            if principal is None:
                raise NotFoundError(f"Principal {principal_id} not found")
            principal_org = principal["organization_id"] if isinstance(principal, dict) else principal[1]
            if str(principal_org) != org:
                raise OrgMismatchError("Principal belongs to another organization")
            cur.execute("UPDATE app.drivers SET principal_id = %s WHERE id = %s;", (principal_id, driver_id))
            conn.commit()
            return {"driver_id": driver_id, "principal_id": principal_id, "organization_id": org}
    except (NotFoundError, OrgMismatchError, DatabaseUnavailableError):
        raise
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        raise BootstrapError(f"Driver link failed: {exc}") from exc
    finally:
        try:
            conn.close()
        except Exception:
            pass
