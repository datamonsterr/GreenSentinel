"""Canonical role routing (S4-ENTRY #296, ADR-025).

Admin -> /organization, driver-only -> /driver, else -> /workspace.
Pure function: no I/O, safe for middleware/client mirroring.
"""

from __future__ import annotations

from collections.abc import Iterable

ORGANIZATION_ROUTE = "/organization"
WORKSPACE_ROUTE = "/workspace"
DRIVER_ROUTE = "/driver"

_ANALYST_ROLES = {"analyst", "fraud_analyst", "senior_analyst", "reviewer", "ops_director", "marketplace_director"}


def resolve_initial_route(roles: Iterable[str] | None, has_org: bool = True) -> str:
    """Return canonical initial route for a principal.

    Priority: admin > /organization; driver-only > /driver; else /workspace.
    ``has_org`` is accepted for contract symmetry; routing is role-driven and
    does not collapse to a default org.
    """
    normalized = {str(r).strip().lower() for r in (roles or []) if str(r).strip()}
    if "admin" in normalized:
        return ORGANIZATION_ROUTE
    if "driver" in normalized and not (normalized & (_ANALYST_ROLES | {"admin"})):
        return DRIVER_ROUTE
    return WORKSPACE_ROUTE


def primary_role_for(roles: Iterable[str] | None) -> str:
    """Canonical primary role: admin | driver (driver-only) | analyst."""
    normalized = {str(r).strip().lower() for r in (roles or []) if str(r).strip()}
    if "admin" in normalized:
        return "admin"
    if "driver" in normalized and not (normalized & (_ANALYST_ROLES | {"admin"})):
        return "driver"
    return "analyst"
