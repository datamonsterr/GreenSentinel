"""Real source adapter contract; external HTTP is the only provider test seam."""

from uuid import uuid4

import pytest
from dotenv import load_dotenv

from src.config import get_settings
from src.models.tool_contracts import ToolExecutionContext
from src.services.tool_execution import execute_tool

pytestmark = pytest.mark.docker


def _is_db_available() -> bool:
    try:
        import psycopg

        load_dotenv(".env", override=False)
        db_url = get_settings().database_url
        if not db_url:
            return False
        with psycopg.connect(db_url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM app.fraud_cases WHERE id = '018f2f4e-a000-7000-8000-000000000001'::uuid LIMIT 1;"
                )
                return bool(cur.fetchone())
    except Exception:
        return False


@pytest.fixture(autouse=True)
def require_db(request):
    non_db_tests = {
        "test_actor_cannot_choose_another_driver_in_model_arguments",
        "test_important_mutation_cannot_be_selected_by_model",
    }
    if request.node.name not in non_db_tests and not _is_db_available():
        pytest.skip("PostgreSQL database with app.fraud_cases schema not available")


def context():
    load_dotenv(".env", override=False)
    get_settings.cache_clear()
    return ToolExecutionContext(
        actor_id="018f2f4e-1000-7000-8000-000000000001",
        organization_id="018f2f4e-0000-7000-8000-000000000001",
        roles=frozenset({"analyst"}),
        case_id="018f2f4e-a000-7000-8000-000000000001",
        driver_id="018f2f4e-3000-7000-8000-000000000001",
        request_id=str(uuid4()),
        run_id=str(uuid4()),
        tool_call_id=str(uuid4()),
        turn_id=str(uuid4()),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("list_cases", {"limit": 2}),
        ("get_driver_history", {}),
        ("inspect_trip_telemetry", {}),
        ("get_case_context", {}),
        ("get_trip_lifecycle_evidence", {}),
        ("compare_trip_routes", {}),
        ("check_system_error_guardrail", {}),
        ("get_dispute_dossier", {}),
        ("check_related_cases_to_vehicle", {}),
        ("get_case_map_snapshot", {}),
    ],
)
async def test_existing_sources_have_real_typed_results(tool, arguments):
    events = []
    result = await execute_tool(tool, arguments, context(), on_event=events.append)
    assert result.status == "succeeded", result.model_dump()
    assert result.data is not None
    assert result.provenance and all(p.source != "app.cases" for p in result.provenance)
    assert len(events) == 2
    assert events[0]["tool_call_id"] == events[-1]["tool_call_id"]


@pytest.mark.asyncio
async def test_actor_cannot_choose_another_driver_in_model_arguments():
    result = await execute_tool("get_driver_history", {"driver_id": "018f2f4e-3000-7000-8000-000000000002"}, context())
    assert result.status == "failed"
    assert result.error.code == "FORBIDDEN"


@pytest.mark.asyncio
async def test_important_mutation_cannot_be_selected_by_model():
    result = await execute_tool("write_ticket_for_driver", {}, context())
    assert result.status == "failed"
    assert result.error.code == "FORBIDDEN"


@pytest.mark.asyncio
async def test_transient_weather_retry_uses_actual_provider_response(monkeypatch):
    import httpx

    attempts = []

    async def provider_boundary(self, url, **kwargs):
        attempts.append(kwargs["params"])
        status = 503 if len(attempts) == 1 else 200
        return httpx.Response(
            status,
            json={
                "hourly": {
                    "time": ["2026-09-22T06:00"],
                    "temperature_2m": [29.1],
                    "precipitation": [0.5],
                    "wind_speed_10m": [8.0],
                },
                "hourly_units": {"temperature_2m": "°C", "precipitation": "mm", "wind_speed_10m": "km/h"},
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", provider_boundary)
    result = await execute_tool("check_weather_condition", {}, context())
    assert result.status == "succeeded"
    assert len(attempts) == 2
    assert result.data["hourly"]["temperature_2m"] == [29.1]
    assert result.data["source_type"] == "historical_reanalysis"
    assert result.provenance[0].kind == "provider"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected_attempts", [(400, 1), (503, 2)])
async def test_provider_failure_never_fabricates_weather(monkeypatch, status, expected_attempts):
    import httpx

    attempts = []

    async def boundary(self, url, **kwargs):
        attempts.append(1)
        return httpx.Response(status, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", boundary)
    result = await execute_tool("check_weather_condition", {}, context())
    assert result.status == "failed"
    assert result.data is None
    assert len(attempts) == expected_attempts
    assert result.error.retryable is (status == 503)


def _caseless_driver_context():
    """A real driver principal with zero cases: no `case_id` bound at all.

    Matches PR #603 Railway preview (Postgres-backed, real Clerk driver) —
    exercised with `APP_ENV` explicitly NOT `test` so the fail-closed
    production path in `_scope`/`build_case_context` runs for real, not the
    test fixture fallback.
    """
    import os

    from src.config import get_settings

    os.environ["APP_ENV"] = "production"
    os.environ["TEST_AUTH_ENABLED"] = "false"
    get_settings.cache_clear()
    return ToolExecutionContext(
        actor_id=str(uuid4()),
        organization_id="018f2f4e-0000-7000-8000-000000000001",
        roles=frozenset({"driver"}),
        case_id=None,
        driver_id=str(uuid4()),
        request_id=str(uuid4()),
        run_id=str(uuid4()),
        tool_call_id=str(uuid4()),
        turn_id=str(uuid4()),
    )


@pytest.fixture
def production_app_env():
    """Run with APP_ENV!=test (production fail-closed path), restored after."""
    import os

    from src.config import get_settings

    prior_env = os.environ.get("APP_ENV")
    prior_auth = os.environ.get("TEST_AUTH_ENABLED")
    yield
    if prior_env is None:
        os.environ.pop("APP_ENV", None)
    else:
        os.environ["APP_ENV"] = prior_env
    if prior_auth is None:
        os.environ.pop("TEST_AUTH_ENABLED", None)
    else:
        os.environ["TEST_AUTH_ENABLED"] = prior_auth
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_query_driver_policy_caseless_driver_production_env_not_a_failure(production_app_env):
    """Bug repro (PR #603): policy lookup for a caseless driver must not fail.

    Previously `search_policy_documents` dispatch unconditionally called the
    analyst case-scoped `build_case_context`, which raises for a driver with
    no case, surfacing "Tool execution failed" in the UI with no logged
    exception.
    """
    ctx = _caseless_driver_context()
    result = await execute_tool("query_driver_policy", {"query": "Điều 12.2 quy định gì về kẹt xe?"}, ctx)
    assert result.status == "succeeded", result.model_dump()
    assert result.data.get("results")


@pytest.mark.asyncio
async def test_list_my_cases_caseless_driver_production_env_not_a_failure(production_app_env):
    """Bug repro (PR #603): a driver with zero cases must get an empty list."""
    ctx = _caseless_driver_context()
    result = await execute_tool("list_my_cases", {}, ctx)
    assert result.status == "succeeded", result.model_dump()
    assert result.data.get("cases") == []


@pytest.mark.asyncio
async def test_list_my_cases_tolerates_model_supplied_null_status_production_env(production_app_env):
    """Bug repro (PR #603): model-supplied `status: null` must not VALIDATION_ERROR."""
    ctx = _caseless_driver_context()
    result = await execute_tool("list_my_cases", {"status": None}, ctx)
    assert result.status == "succeeded", result.model_dump()


@pytest.mark.asyncio
async def test_list_my_trips_caseless_driver_production_env_not_a_failure(production_app_env):
    ctx = _caseless_driver_context()
    result = await execute_tool("list_my_trips", {}, ctx)
    assert result.status == "succeeded", result.model_dump()


@pytest.mark.asyncio
async def test_question_tool_creates_a_recoverable_interaction():
    result = await execute_tool(
        "ask_interactive_question",
        {
            "question_id_stable": str(uuid4()),
            "question_kind": "yes_no",
            "actor_target": "analyst",
            "question_text": "Đã kiểm tra dữ liệu hành trình chưa?",
        },
        context(),
    )
    assert result.status == "succeeded", result.model_dump()
    assert result.data["question_id"]
    assert result.data["status"] == "pending"
