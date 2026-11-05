"""Unit: canonical role routing (S4-ENTRY #296)."""

from src.services.role_routing import primary_role_for, resolve_initial_route


def test_admin_routes_organization():
    assert resolve_initial_route(["admin"], True) == "/organization"
    assert resolve_initial_route(["analyst", "admin"], True) == "/organization"


def test_driver_only_routes_driver():
    assert resolve_initial_route(["driver"], True) == "/driver"


def test_analyst_routes_workspace():
    assert resolve_initial_route(["analyst"], True) == "/workspace"
    assert resolve_initial_route(["fraud_analyst"], True) == "/workspace"
    assert resolve_initial_route(["driver", "analyst"], True) == "/workspace"
    assert resolve_initial_route([], True) == "/workspace"
    assert resolve_initial_route(None, False) == "/workspace"


def test_primary_roles():
    assert primary_role_for(["admin"]) == "admin"
    assert primary_role_for(["driver"]) == "driver"
    assert primary_role_for(["driver", "analyst"]) == "analyst"
    assert primary_role_for(["fraud_analyst"]) == "analyst"
