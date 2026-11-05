from uuid import uuid4

import pytest

from src.models.tool_contracts import ToolExecutionContext
from src.services import tool_execution
from src.services.tool_execution import execute_tool


def _context():
    return ToolExecutionContext(
        actor_id="actor",
        organization_id="org",
        roles=frozenset({"analyst"}),
        case_id="case",
        driver_id="driver",
        request_id=str(uuid4()),
        run_id=str(uuid4()),
        tool_call_id=str(uuid4()),
        turn_id=str(uuid4()),
    )


@pytest.mark.asyncio
async def test_policy_search_constrains_chunks_to_snapshot_version(monkeypatch):
    calls = []

    async def context(_ctx):
        return {"evidence_snapshot": {"id": "snap", "policy_version_id": "version-a"}}

    def rows(query, params):
        calls.append((query, params))
        return [
            {
                "id": "chunk-a",
                "policy_version_id": "version-a",
                "source_ref": "handbook",
                "section_ref": "§1",
                "content": "Exact clause text",
                "version": "2026.1",
                "effective_from": None,
                "effective_to": None,
                "is_demo_policy": False,
            }
        ]

    monkeypatch.setattr(tool_execution, "build_case_context", context)
    monkeypatch.setattr(tool_execution, "_rows", rows)
    data, _ = await tool_execution._dispatch("search_policy_documents", {"query": "clause"}, _context(), {})

    assert calls[0][1] == ("version-a", "version-a", "%clause%")
    assert "pc.policy_version_id=%s::uuid" in calls[0][0]
    assert data["results"][0]["snippet"] == "Exact clause text"
    assert data["results"][0]["section_ref"] == "§1"
    assert data["results"][0]["policy_version_id"] == "version-a"


@pytest.mark.asyncio
@pytest.mark.parametrize("snapshot", [{}, {"policy_version_id": None}])
async def test_policy_search_abstains_without_snapshot_policy(monkeypatch, snapshot):
    async def context(_ctx):
        return {"evidence_snapshot": snapshot}

    monkeypatch.setattr(tool_execution, "build_case_context", context)
    data, _ = await tool_execution._dispatch("search_policy_documents", {"query": "clause"}, _context(), {})

    assert data["status"] == "uncertain"
    assert data["results"] == []
    assert data["abstention"]


@pytest.mark.asyncio
async def test_policy_search_abstains_when_version_has_no_match(monkeypatch):
    async def context(_ctx):
        return {"evidence_snapshot": {"id": "snap", "policy_version_id": "version-a"}}

    monkeypatch.setattr(tool_execution, "build_case_context", context)
    monkeypatch.setattr(tool_execution, "_rows", lambda query, params: [])
    data, _ = await tool_execution._dispatch("search_policy_documents", {"query": "missing"}, _context(), {})

    assert data["status"] == "uncertain"
    assert data["citations"] == []
    assert data["abstention"]


@pytest.mark.asyncio
async def test_execute_tool_accepts_versioned_policy_contract(monkeypatch):
    async def context(_ctx):
        return {"evidence_snapshot": {"id": "snap", "policy_version_id": "version-a"}}

    monkeypatch.setattr(tool_execution, "build_case_context", context)
    monkeypatch.setattr(tool_execution, "_scope", lambda _ctx: {})
    monkeypatch.setattr(tool_execution, "_rows", lambda query, params: [])
    result = await execute_tool("search_policy_documents", {"query": "missing_%"}, _context())

    assert result.status == "succeeded"
    assert result.data["case_id"] == "case"
    assert result.data["status"] == "uncertain"
    assert result.data["abstention"]
