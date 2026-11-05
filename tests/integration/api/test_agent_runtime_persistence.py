"""Migrated DB proof; only model HTTP and signed-session verification are test seams."""

from uuid import uuid4

import pytest
from dotenv import load_dotenv
from google.genai import types
from httpx import ASGITransport, AsyncClient

from src.api.auth import Principal, require_principal
from src.config import get_settings
from src.main import app

pytestmark = pytest.mark.docker

CASE = "018f2f4e-a000-7000-8000-000000000001"
OWNER = "018f2f4e-1000-7000-8000-000000000001"
ORG = "018f2f4e-0000-7000-8000-000000000001"


@pytest.mark.asyncio
async def test_completed_turn_reloads_and_replays_without_generation(monkeypatch):
    from tests.integration.services.test_canonical_tool_execution import _is_db_available

    if not _is_db_available():
        pytest.skip("PostgreSQL database with app.fraud_cases schema not available")
    load_dotenv(".env", override=False)
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-provider-key")
    get_settings.cache_clear()
    actor = Principal(OWNER, ORG, frozenset({"analyst"}))
    app.dependency_overrides[require_principal] = lambda: actor
    calls = []

    async def model_boundary(*args, **kwargs):
        calls.append(1)
        return types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        role="model", parts=[types.Part.from_text(text="Dữ liệu đã ghi nhận; quyết định chờ analyst.")]
                    )
                )
            ]
        )

    monkeypatch.setattr("google.genai.models.AsyncModels.generate_content", model_boundary)
    tid = str(uuid4())
    payload = {"query": "Tóm tắt vụ việc", "turn_id": tid, "event_schema_version": "1.1"}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            first = await c.post(f"/api/v1/cases/{CASE}/agent-runtime/stream", json=payload)
            assert first.status_code == 200
            assert "run.completed" in first.text
            saved = await c.get(f"/api/v1/cases/{CASE}/agent-runtime/state", params={"turn_id": tid})
            assert saved.status_code == 200
            assert saved.json()["turns"][0]["status"] == "completed"
            replay = await c.post(f"/api/v1/cases/{CASE}/agent-runtime/stream", json=payload)
            assert replay.text == first.text
            # 2 calls on initial generation: agent turn + answer formatter. No calls on replay.
            assert len(calls) == 2
            conflict = await c.post(f"/api/v1/cases/{CASE}/agent-runtime/stream", json={**payload, "query": "Changed"})
            assert conflict.status_code == 409
    finally:
        app.dependency_overrides.pop(require_principal, None)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_driver_surface_rejects_analyst_even_with_verified_session():
    app.dependency_overrides[require_principal] = lambda: Principal(OWNER, ORG, frozenset({"analyst"}))
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                f"/api/v1/driver/cases/{CASE}/chat/stream", json={"message": "Test", "event_schema_version": "1.1"}
            )
            assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(require_principal, None)
