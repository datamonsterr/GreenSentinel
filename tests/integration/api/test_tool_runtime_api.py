"""API contract tests for tool runtime and event stream negotiation (legacy vs 1.1)."""

from uuid import uuid4

import pytest
from dotenv import load_dotenv
from google.genai import types
from httpx import ASGITransport, AsyncClient

from src.api.auth import Principal, require_principal
from src.config import get_settings
from src.main import app

pytestmark = pytest.mark.docker

CASE_ID = "018f2f4e-a000-7000-8000-000000000001"
ANALYST_ID = "018f2f4e-1000-7000-8000-000000000001"
DRIVER_PRINCIPAL_ID = "42d60525-ae3c-4fd0-b6eb-42f5b16bd1d9"
DRIVER_ID = "018f2f4e-3000-7000-8000-000000000001"
ORG_ID = "018f2f4e-0000-7000-8000-000000000001"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    from tests.integration.services.test_canonical_tool_execution import _is_db_available

    if not _is_db_available():
        pytest.skip("PostgreSQL database with app.fraud_cases schema not available")
    load_dotenv(".env", override=False)
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-provider-key")
    get_settings.cache_clear()
    yield
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_policy_chat_stream_negotiates_v1_1_canonical_events(monkeypatch):
    actor = Principal(ANALYST_ID, ORG_ID, frozenset({"analyst"}))
    app.dependency_overrides[require_principal] = lambda: actor

    async def mock_generate_content(*args, **kwargs):
        return types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        role="model",
                        parts=[types.Part.from_text(text="Căn cứ theo điều 14.2 quy định vi phạm.")],
                    )
                )
            ]
        )

    monkeypatch.setattr("google.genai.models.AsyncModels.generate_content", mock_generate_content)

    turn_id = str(uuid4())
    payload = {
        "query": "Tra cứu quy chế",
        "case_id": CASE_ID,
        "turn_id": turn_id,
        "event_schema_version": "1.1",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/v1/policy/chat/stream", json=payload)
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/event-stream")

        text = res.text
        assert "schema_version" in text
        assert "1.1" in text
        assert "run.completed" in text
        assert "text.delta" in text


@pytest.mark.asyncio
async def test_policy_chat_stream_preserves_legacy_frames_when_unnegotiated(monkeypatch):
    actor = Principal(ANALYST_ID, ORG_ID, frozenset({"analyst"}))
    app.dependency_overrides[require_principal] = lambda: actor

    turn_id = str(uuid4())
    payload = {
        "query": "Giải thích quy chế",
        "case_id": CASE_ID,
        "turn_id": turn_id,
        # No event_schema_version: defaults to legacy
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/v1/policy/chat/stream", json=payload)
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/event-stream")

        text = res.text
        assert "event: text_delta" in text or "event: done" in text or "event: citation" in text


@pytest.mark.asyncio
async def test_driver_chat_stream_negotiates_v1_1_and_enforces_driver_role(monkeypatch):
    import psycopg
    from psycopg.rows import dict_row

    db_url = get_settings().database_url
    p_id = DRIVER_PRINCIPAL_ID
    d_id = DRIVER_ID
    o_id = ORG_ID

    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT c.id, c.organization_id, a.driver_id, d.principal_id
                   FROM app.fraud_cases c
                   JOIN app.trip_assignments a ON a.id = c.assignment_id
                   JOIN app.drivers d ON d.id = a.driver_id
                   WHERE c.id = %s::uuid""",
                (CASE_ID,),
            )
            row = cur.fetchone()
            if row:
                d_id = str(row["driver_id"])
                o_id = str(row["organization_id"])
                if row.get("principal_id"):
                    p_id = str(row["principal_id"])
                else:
                    p_id = str(uuid4())
                    cur.execute(
                        "INSERT INTO app.principals (id, organization_id, external_subject, display_name, status) VALUES (%s, %s, %s, 'Driver Principal', 'active')",
                        (p_id, o_id, f"synthetic-driver-{p_id}"),
                    )
                    cur.execute(
                        "INSERT INTO app.principal_roles (principal_id, role) VALUES (%s, 'driver') ON CONFLICT DO NOTHING",
                        (p_id,),
                    )
                    cur.execute(
                        "UPDATE app.drivers SET principal_id = %s WHERE id = %s",
                        (p_id, d_id),
                    )
                    conn.commit()

    driver_principal = Principal(p_id, o_id, frozenset({"driver"}), driver_id=d_id)
    app.dependency_overrides[require_principal] = lambda: driver_principal

    async def mock_generate_content(*args, **kwargs):
        return types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        role="model",
                        parts=[types.Part.from_text(text="Hệ thống đã nhận giải trình.")],
                    )
                )
            ]
        )

    monkeypatch.setattr("google.genai.models.AsyncModels.generate_content", mock_generate_content)

    turn_id = str(uuid4())
    payload = {
        "case_id": CASE_ID,
        "driver_id": d_id,
        "message": "Tôi bị kẹt xe",
        "turn_id": turn_id,
        "event_schema_version": "1.1",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(f"/api/v1/driver/cases/{CASE_ID}/chat/stream", json=payload)
        assert res.status_code == 200
        text = res.text
        assert "schema_version" in text
        assert "1.1" in text
        assert "run.completed" in text


@pytest.mark.asyncio
async def test_unauthenticated_requests_are_rejected_in_production(monkeypatch):
    app.dependency_overrides.clear()
    monkeypatch.setenv("APP_ENV", "production")
    get_settings.cache_clear()
    turn_id = str(uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/v1/policy/chat/stream",
            json={"query": "test", "case_id": CASE_ID, "turn_id": turn_id, "event_schema_version": "1.1"},
        )
        assert res.status_code == 401
