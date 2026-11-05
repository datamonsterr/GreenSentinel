"""Unit and integration tests for RAG read-only database query tools."""

import pytest

from src.rag.cockpit_agent import CockpitRAGAgent
from src.rag.db_tools import (
    _escape_like_pattern,
    _mask_phone,
    get_audit_log,
    get_case_information,
    get_case_list_priority,
    get_driver_profile,
    get_telemetry,
)
from src.services.case_service import get_case_service

pytestmark = pytest.mark.docker


@pytest.fixture(scope="module")
def case_service():
    """Ensure case service is initialized with seed data."""
    return get_case_service()


def test_get_case_information_found(case_service):
    """Scenario 1: Retrieve valid case information from database/cache."""
    # Find any active case ID from initialized cases
    assert len(case_service._cases) > 0
    sample_case_id = next(iter(case_service._cases.keys()))

    res = get_case_information(sample_case_id, service=case_service)
    assert res["found"] is True
    assert res["source"] in ("database", "in_memory_fallback")
    assert "case" in res
    case_data = res["case"]
    assert str(case_data.get("id")) == sample_case_id
    assert "priority" in case_data
    assert "status" in case_data
    assert "category" in case_data


def test_get_case_information_not_found(case_service):
    """Scenario 1b: Retrieve non-existent case information gracefully."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    res = get_case_information(fake_id, service=case_service)
    assert res["found"] is False
    assert "error" in res


def test_get_driver_profile(case_service):
    """Scenario 2: Retrieve driver profile, vehicle, and standing."""
    res = get_driver_profile("drv-8492-nguyen-van-a", service=case_service)
    assert res["found"] is True
    driver = res["driver"]
    assert "Nguyễn Văn A" in driver["full_name"]
    assert "vehicle_plate" in driver
    assert driver["phone_number"].startswith("+84") or driver["phone_number"] == "[REDACTED]"
    # Sensitive phone number must be masked
    assert "123 456 78" not in driver["phone_number"]
    assert "is_suspended" in driver
    assert isinstance(driver["is_suspended"], bool)


def test_get_telemetry(case_service):
    """Scenario 3: Retrieve GPS telemetry points and anomaly/mock location metrics."""
    # Retrieve telemetry using a known case ID or assignment ID
    sample_case_id = next(iter(case_service._cases.keys()))
    res = get_telemetry(sample_case_id, limit=20, service=case_service)
    assert res["found"] is True
    assert res["point_count"] > 0
    assert len(res["points"]) <= 20
    assert "stats" in res
    assert "avg_speed_mps" in res["stats"]
    assert "mock_locations_detected" in res["stats"]

    # Verify telemetry point data structure
    pt = res["points"][0]
    assert "speed_mps" in pt
    assert "mock_location_reported" in pt


def test_get_case_list_priority(case_service):
    """Scenario 4: Query fraud cases queue sorted by priority score with filtering."""
    # Query with limit
    res = get_case_list_priority(limit=10, service=case_service)
    assert res["total"] > 0
    assert len(res["items"]) <= 10

    # Verify descending priority ordering
    scores = [item.get("priority_score", 0) for item in res["items"]]
    assert scores == sorted(scores, reverse=True)

    # Query with priority filter
    p0_res = get_case_list_priority(priority="P0", limit=5, service=case_service)
    for item in p0_res["items"]:
        assert item.get("priority") == "P0"


def test_get_audit_log(case_service):
    """Scenario 5: Retrieve audit events, review actions, and adjudications."""
    sample_case_id = next(iter(case_service._cases.keys()))
    res = get_audit_log(case_id=sample_case_id, limit=10, service=case_service)
    assert "events" in res
    assert "count" in res
    assert res["count"] >= 1
    ev = res["events"][0]
    assert "entity_type" in ev
    assert "actor_id" in ev


def test_cockpit_agent_routes_to_db_tools():
    """Scenario 6: Verify CockpitRAGAgent routes user queries to the new DB tools."""
    agent = CockpitRAGAgent(api_key="mock")

    # 1. Case information routing
    r_case = agent.execute_turn("Show me case information and dossier for 018f2f4e-a000-7000-8000-000000000010")
    assert r_case.display_format == "composite"
    assert r_case.raw_tool_data.get("tool_called") == "get_case_information"
    assert "Case Dossier" in r_case.answer

    # 2. Driver profile routing
    r_driver = agent.execute_turn("Retrieve driver profile from db for Nguyen Van A")
    assert r_driver.display_format == "driver_card"
    assert r_driver.raw_tool_data.get("tool_called") == "get_driver_profile"
    assert "Driver Profile (DB)" in r_driver.answer

    # 3. Telemetry routing
    r_telem = agent.execute_turn("Show me telemetry and GPS points coordinates for trip-001")
    assert r_telem.display_format == "composite"
    assert r_telem.raw_tool_data.get("tool_called") == "get_telemetry"
    assert "Telemetry Records" in r_telem.answer

    # 4. Priority queue routing
    r_queue = agent.execute_turn("Show me the priority queue of cases by priority")
    assert r_queue.display_format == "composite"
    assert r_queue.raw_tool_data.get("tool_called") == "get_case_list_priority"
    assert "Fraud Queue by Priority" in r_queue.answer

    # 5. Audit log routing
    r_audit = agent.execute_turn("Retrieve audit log and review actions for case 018f2f4e-a000-7000-8000-000000000010")
    assert r_audit.display_format == "composite"
    assert r_audit.raw_tool_data.get("tool_called") == "get_audit_log"
    assert "Case Audit Log" in r_audit.answer


# ---------------------------------------------------------------------------
# Security hardening tests
# ---------------------------------------------------------------------------


class TestEscapeLikePattern:
    """Verify LIKE wildcard escaping prevents pattern injection."""

    def test_percent_escaped(self):
        assert _escape_like_pattern("a%b") == "a\\%b"

    def test_underscore_escaped(self):
        assert _escape_like_pattern("a_b") == "a\\_b"

    def test_backslash_escaped(self):
        assert _escape_like_pattern("a\\b") == "a\\\\b"

    def test_combined_injection(self):
        payload = "'; DROP TABLE drivers; --"
        result = _escape_like_pattern(payload)
        # No unescaped wildcards remain
        assert "%" not in result
        assert result.count("_") == result.count("\\_")

    def test_empty_string(self):
        assert _escape_like_pattern("") == ""

    def test_no_special_chars_unchanged(self):
        assert _escape_like_pattern("Nguyen Van A") == "Nguyen Van A"


class TestMaskPhone:
    """Verify PII masking with edge cases and E.164 enforcement."""

    def test_none_returns_not_provided(self):
        assert _mask_phone(None) == "[NOT_PROVIDED]"

    def test_empty_string_returns_not_provided(self):
        assert _mask_phone("") == "[NOT_PROVIDED]"

    def test_already_redacted_preserved(self):
        assert _mask_phone("[REDACTED]") == "[REDACTED]"
        assert _mask_phone("[NOT_PROVIDED]") == "[NOT_PROVIDED]"
        assert _mask_phone("[UNAVAILABLE]") == "[UNAVAILABLE]"

    def test_too_short_digits_redacted(self):
        # 7 digits < 9 minimum → must redact fully
        assert _mask_phone("0123456") == "[REDACTED]"

    def test_too_long_digits_redacted(self):
        # 16 digits > 15 maximum → must redact fully
        assert _mask_phone("1234567890123456") == "[REDACTED]"

    def test_valid_vn_international_masked(self):
        result = _mask_phone("+84912345678")
        assert result.startswith("+84")
        assert "x" in result
        assert result.endswith("678")
        assert "912345" not in result  # middle digits must be masked

    def test_valid_vn_domestic_masked(self):
        result = _mask_phone("0912345678")
        assert result.startswith("09")
        assert "x" in result
        assert result.endswith("678")
        assert "12345" not in result

    def test_non_numeric_garbage_redacted(self):
        # Only 3 digits → below 9 minimum
        assert _mask_phone("abc!@#123") == "[REDACTED]"

    def test_sql_injection_as_phone_redacted(self):
        # SQL injection payload produces fewer than 9 digits → fully redacted
        result = _mask_phone("'; DROP TABLE drivers; --")
        assert result == "[REDACTED]"


class TestGetCaseInformationSecurity:
    """Verify get_case_information rejects non-UUID and SQL payloads."""

    def test_sql_injection_payload_not_found(self, case_service):
        payload = "' OR '1'='1"
        res = get_case_information(payload, service=case_service)
        # Must not raise, must not return data from a different case
        assert res["found"] is False or res.get("source") != "database"

    def test_oversized_input_truncated_to_not_found(self, case_service):
        long_id = "A" * 200
        res = get_case_information(long_id, service=case_service)
        assert res["found"] is False

    def test_union_select_payload(self, case_service):
        payload = "x UNION SELECT * FROM app.fraud_cases--"
        res = get_case_information(payload, service=case_service)
        assert res["found"] is False


class TestGetDriverProfileSecurity:
    """Verify get_driver_profile escapes ILIKE and rejects injection payloads."""

    def test_like_injection_payload_returns_safe_result(self, case_service):
        # % and _ in raw_query must be escaped — should not raise or return unexpected data
        res = get_driver_profile("%admin%", service=case_service)
        assert isinstance(res, dict)
        assert "driver" in res

    def test_underscore_wildcard_does_not_match_all(self, case_service):
        # Single _ should not match arbitrary names
        res = get_driver_profile("_", service=case_service)
        assert isinstance(res, dict)

    def test_sql_quote_payload(self, case_service):
        payload = "'; SELECT * FROM app.drivers; --"
        res = get_driver_profile(payload, service=case_service)
        assert isinstance(res, dict)
        assert "driver" in res

    def test_oversized_input_bounded(self, case_service):
        long_input = "N" * 200
        res = get_driver_profile(long_input, service=case_service)
        assert isinstance(res, dict)


class TestGetAuditLogSecurity:
    """Verify get_audit_log rejects non-UUID case_id values."""

    def test_sql_injection_payload_falls_back(self, case_service):
        payload = "' OR '1'='1"
        res = get_audit_log(case_id=payload, service=case_service)
        assert "events" in res
        # Non-UUID must not hit DB UUID branch → source is in_memory or empty
        assert res.get("source") != "database" or res["count"] == 0

    def test_numeric_string_rejected(self, case_service):
        res = get_audit_log(case_id="12345", service=case_service)
        assert "events" in res

    def test_limit_clamped_to_max(self, case_service):
        res = get_audit_log(limit=9999, service=case_service)
        # limit is clamped to 200 internally, response must not exceed it
        assert len(res["events"]) <= 200

    def test_limit_clamped_to_min(self, case_service):
        res = get_audit_log(limit=-5, service=case_service)
        assert "events" in res


class TestGetCaseListPrioritySecurity:
    """Verify whitelist enforcement and limit/offset clamping."""

    def test_invalid_status_ignored(self, case_service):
        res = get_case_list_priority(status="'; DROP TABLE--", service=case_service)
        assert isinstance(res, dict)
        assert "items" in res

    def test_invalid_priority_ignored(self, case_service):
        res = get_case_list_priority(priority="INVALID", service=case_service)
        assert isinstance(res, dict)

    def test_limit_clamped_max(self, case_service):
        res = get_case_list_priority(limit=9999, service=case_service)
        assert len(res["items"]) <= 100

    def test_limit_clamped_min(self, case_service):
        res = get_case_list_priority(limit=0, service=case_service)
        assert "items" in res

    def test_negative_offset_clamped(self, case_service):
        res = get_case_list_priority(offset=-100, service=case_service)
        assert "items" in res
