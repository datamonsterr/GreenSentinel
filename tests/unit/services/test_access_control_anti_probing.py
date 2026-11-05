"""require_case_scope's anti_probing_driver_mismatch flag (Issue #157).

Merge note: main independently hardened require_case_scope's in-memory
(no-DB, test-only) fallback path to reject a cross-driver `driver_id` with
403 "Driver is not assigned to this case"
(test_driver_escalation_transitions.py calls require_case_scope directly
and depends on that exact 403). The driver-app redesign (Issue #157)
separately requires driver-self-service endpoints (chat, chat-stream,
session) to never leak case existence to a non-owner via 403 — always 404
(see tests/unit/api/test_driver_case_chat_ownership.py). Rebasing combined
both; `anti_probing_driver_mismatch` lets each caller opt into the 404
contract explicitly instead of one call site's behavior silently winning.
The real-DB path is never affected by this flag.
"""

import pytest
from fastapi import HTTPException

from src.services.access_control import require_case_scope


class _FakeSettings:
    app_env = "test"
    test_auth_enabled = True


class _FakeService:
    def __init__(self, cases):
        self.settings = _FakeSettings()
        self._cases = cases
        self._assignments = {}

    def _get_db_connection(self):
        return None

    def _resolve_case_id(self, case_id):
        return case_id


def test_default_raises_403_for_driver_mismatch():
    service = _FakeService({"case-1": {"organization_id": "org-1", "driver_id": "drv-owner"}})
    with pytest.raises(HTTPException) as exc_info:
        require_case_scope(service, "case-1", "org-1", driver_id="drv-intruder")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Driver is not assigned to this case"


def test_anti_probing_flag_converts_driver_mismatch_to_404():
    service = _FakeService({"case-1": {"organization_id": "org-1", "driver_id": "drv-owner"}})
    with pytest.raises(HTTPException) as exc_info:
        require_case_scope(service, "case-1", "org-1", driver_id="drv-intruder", anti_probing_driver_mismatch=True)
    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail.lower()


def test_anti_probing_flag_does_not_alter_org_mismatch():
    service = _FakeService({"case-1": {"organization_id": "org-1", "driver_id": "drv-owner"}})
    with pytest.raises(HTTPException) as exc_info:
        require_case_scope(service, "case-1", "org-2", driver_id="drv-owner", anti_probing_driver_mismatch=True)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Case access denied"


def test_anti_probing_flag_allows_owner():
    service = _FakeService({"case-1": {"organization_id": "org-1", "driver_id": "drv-owner"}})
    require_case_scope(service, "case-1", "org-1", driver_id="drv-owner", anti_probing_driver_mismatch=True)
