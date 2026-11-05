"""RED tests for Issue #483: confirmation-gated accept/reject flow.

- LLM path cannot submit without a valid token.
- Token cannot be reused (single-use).
- Token for case A fails on case B.
- Draft persists and can be resumed.
- Submitted statement appears on timeline and escalates (analyst_escalated).
- Acknowledge records event, routes to analyst, never sanctions.
"""

from __future__ import annotations

import pytest

from src.services.scenario_seeder import ScenarioSeeder


@pytest.fixture(autouse=True)
def seed_scenarios():
    seeder = ScenarioSeeder()
    seeder.seed_in_memory()
    yield
    seeder.clean_in_memory()


def _owned_case_driver():
    return ("018f2f4e-a000-7000-8000-000000000001", "018f2f4e-b300-7000-8000-000000000001")


@pytest.mark.asyncio
async def test_llm_cannot_submit_without_token():
    from src.agents.tools.driver_tools import submit_driver_statement

    case_id, driver_id = _owned_case_driver()
    res = await submit_driver_statement.ainvoke(
        {
            "case_id": case_id,
            "driver_id": driver_id,
            "reason": "Flooded road, police redirect",
            "claim_type": "weather",
        }
    )
    assert isinstance(res, dict)
    assert res.get("status") in ("failed", "error") or "error" in res or "confirmation" in str(res).lower()


@pytest.mark.asyncio
async def test_token_single_use_and_case_binding():
    from src.services.driver_dispute_service import get_driver_dispute_service

    svc = get_driver_dispute_service()
    case_id, driver_id = _owned_case_driver()
    token = await svc.issue_confirmation_token(
        case_id=case_id, driver_id=driver_id, action="submit_statement", draft_hash="abc"
    )
    assert token

    ok1 = await svc.submit_statement_with_token(
        case_id=case_id,
        driver_id=driver_id,
        confirmation_token=token,
        reason_summary="Flooded road",
        evidence=[],
    )
    assert ok1.get("status") == "submitted"

    # Reuse must fail
    ok2 = await svc.submit_statement_with_token(
        case_id=case_id,
        driver_id=driver_id,
        confirmation_token=token,
        reason_summary="Flooded road",
        evidence=[],
    )
    assert ok2.get("status") == "failed"

    # Token for case A fails on case B
    token_b = await svc.issue_confirmation_token(
        case_id=case_id, driver_id=driver_id, action="submit_statement", draft_hash="abc"
    )
    other_case = "018f2f4e-a000-7000-8000-000000000002"
    cross = await svc.submit_statement_with_token(
        case_id=other_case,
        driver_id=driver_id,
        confirmation_token=token_b,
        reason_summary="x",
        evidence=[],
    )
    assert cross.get("status") == "failed"


@pytest.mark.asyncio
async def test_acknowledge_requires_token_and_never_sanctions():
    from src.agents.tools.driver_tools import acknowledge_violation

    case_id, driver_id = _owned_case_driver()
    res = await acknowledge_violation.ainvoke(
        {"case_id": case_id, "driver_id": driver_id, "confirmation_token": "bogus"}
    )
    assert res.get("status") == "failed"
    assert "sanction" not in str(res.get("sanction_action") or "").lower() or res.get("sanction_action") in (None, "")


@pytest.mark.asyncio
async def test_draft_persist_and_resume():
    from src.services.driver_dispute_service import get_driver_dispute_service

    svc = get_driver_dispute_service()
    case_id, driver_id = _owned_case_driver()
    await svc.save_statement_draft(case_id=case_id, driver_id=driver_id, draft={"reason": "flood"})
    got = await svc.get_statement_draft(case_id=case_id, driver_id=driver_id)
    assert got and got.get("reason") == "flood"


@pytest.mark.asyncio
async def test_statement_sets_analyst_escalated_and_timeline():
    from src.services.driver_dispute_service import get_driver_dispute_service

    svc = get_driver_dispute_service()
    case_id, driver_id = _owned_case_driver()
    token = await svc.issue_confirmation_token(
        case_id=case_id, driver_id=driver_id, action="submit_statement", draft_hash="h"
    )
    res = await svc.submit_statement_with_token(
        case_id=case_id,
        driver_id=driver_id,
        confirmation_token=token,
        reason_summary="Flooded Nguyen Huu Canh, police redirect via Dien Bien Phu",
        evidence=[{"kind": "weather", "summary": "heavy rain"}],
    )
    assert res.get("dispute_status") == "analyst_escalated"
    entries = svc.get_audit_entries(case_id)
    assert any("statement" in str(e.get("action", "")).lower() for e in entries)


def test_confirmation_block_sanitizer():
    from src.services.answer_formatter import normalize_whitelist, sanitize_driver_blocks

    wl = normalize_whitelist({"case_ids": ["c1"], "driver_ids": [], "trip_ids": [], "citation_ids": []})
    blocks = sanitize_driver_blocks(
        [
            {
                "type": "confirmation",
                "action": "submit_statement",
                "checklist": [
                    {"key": "incident_type", "ok": True},
                    {"key": "description", "ok": True},
                    {"key": "evidence", "ok": True},
                ],
                "summary": "Flood detour via Dien Bien Phu",
            }
        ],
        wl,
    )
    assert blocks and blocks[0]["type"] == "confirmation"
