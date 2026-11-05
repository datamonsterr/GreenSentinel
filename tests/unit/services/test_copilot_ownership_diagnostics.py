from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import psycopg
import pytest
from fastapi import HTTPException

import src.services.agent_runtime as runtime
from src.services.agent_runtime import _diagnose_failure, authorize_case


def test_authorize_case_requires_principal():
    with pytest.raises(HTTPException) as exc_info:
        authorize_case(None, str(uuid4()))
    assert exc_info.value.status_code == 401


def test_authorize_case_rejects_malformed_case_id():
    principal = SimpleNamespace(id="p1", organization_id="org1", roles=frozenset({"analyst"}))
    with pytest.raises(HTTPException) as exc_info:
        authorize_case(principal, "invalid-uuid")
    assert exc_info.value.status_code == 404


def _setup_mock_db(row):
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = row
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    return mock_conn


def test_authorize_case_rejects_missing_case():
    principal = SimpleNamespace(id="p1", organization_id="org1", roles=frozenset({"analyst"}))
    mock_conn = _setup_mock_db(None)

    with patch.object(runtime, "_connection", return_value=mock_conn):
        with pytest.raises(HTTPException) as exc_info:
            authorize_case(principal, str(uuid4()))
        assert exc_info.value.status_code == 404


def test_authorize_case_rejects_cross_tenant_access():
    principal = SimpleNamespace(id="p1", organization_id="org-analyst", roles=frozenset({"analyst"}))
    case_row = {
        "id": str(uuid4()),
        "organization_id": "org-other",
        "assigned_analyst_id": "p1",
        "driver_id": "drv1",
        "driver_principal_id": None,
    }
    mock_conn = _setup_mock_db(case_row)

    with patch.object(runtime, "_connection", return_value=mock_conn):
        with pytest.raises(HTTPException) as exc_info:
            authorize_case(principal, case_row["id"])
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Case access denied"


def test_authorize_case_rejects_unclaimed_or_other_analyst_case():
    principal = SimpleNamespace(id="analyst-1", organization_id="org1", roles=frozenset({"analyst", "fraud_analyst"}))
    # Unclaimed case: assigned_analyst_id is None
    case_row = {
        "id": str(uuid4()),
        "organization_id": "org1",
        "assigned_analyst_id": None,
        "driver_id": "drv1",
        "driver_principal_id": None,
    }
    mock_conn = _setup_mock_db(case_row)

    with patch.object(runtime, "_connection", return_value=mock_conn):
        with pytest.raises(HTTPException) as exc_info:
            authorize_case(principal, case_row["id"])
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Case access denied"

    # Claimed by other analyst
    case_row["assigned_analyst_id"] = "analyst-other"
    mock_conn = _setup_mock_db(case_row)
    with patch.object(runtime, "_connection", return_value=mock_conn):
        with pytest.raises(HTTPException) as exc_info:
            authorize_case(principal, case_row["id"])
        assert exc_info.value.status_code == 403


def test_authorize_case_permits_assigned_analyst_and_admin():
    analyst = SimpleNamespace(id="analyst-1", organization_id="org1", roles=frozenset({"analyst", "fraud_analyst"}))
    case_row = {
        "id": str(uuid4()),
        "organization_id": "org1",
        "assigned_analyst_id": "analyst-1",
        "driver_id": "drv1",
        "driver_principal_id": None,
    }
    mock_conn = _setup_mock_db(case_row)

    with patch.object(runtime, "_connection", return_value=mock_conn):
        authorized = authorize_case(analyst, case_row["id"])
        assert authorized["id"] == case_row["id"]

    # Admin permits even if unassigned
    admin = SimpleNamespace(id="admin-1", organization_id="org1", roles=frozenset({"admin"}))
    case_row["assigned_analyst_id"] = None
    mock_conn = _setup_mock_db(case_row)
    with patch.object(runtime, "_connection", return_value=mock_conn):
        authorized_admin = authorize_case(admin, case_row["id"])
        assert authorized_admin["id"] == case_row["id"]


def test_diagnose_failure_maps_safely_without_leaking_credentials():
    # 1. Permission / Forbidden
    code, msg, retry = _diagnose_failure(PermissionError("analyst is not the assigned case owner"))
    assert code == "FORBIDDEN"
    assert "quyền" in msg.lower()
    assert not retry

    # 2. HTTP 403
    code, msg, retry = _diagnose_failure(HTTPException(403, "Case access denied"))
    assert code == "FORBIDDEN"
    assert not retry

    # 3. HTTP 404
    code, msg, retry = _diagnose_failure(HTTPException(404, "Case not found"))
    assert code == "NOT_FOUND"
    assert not retry

    # 4. Timeout
    code, msg, retry = _diagnose_failure(TimeoutError("Model call timed out"))
    assert code == "PROVIDER_TIMEOUT"
    assert retry

    # 5. Database error with secret in string representation
    db_err = psycopg.OperationalError("connection to postgresql://postgres:SUPER_SECRET_PASSWORD@db:5432 failed")
    code, msg, retry = _diagnose_failure(db_err)
    assert code == "PERSISTENCE_UNAVAILABLE"
    assert "SUPER_SECRET_PASSWORD" not in msg
    assert retry

    # 6. Generic exception
    code, msg, retry = _diagnose_failure(RuntimeError("Unexpected LLM syntax error"))
    assert code == "PROVIDER_UNAVAILABLE"
    assert "Unexpected LLM syntax error" not in msg
    assert retry
