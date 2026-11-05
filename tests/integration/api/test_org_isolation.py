"""Two-tenant org isolation contracts for S4-TENANT #294 (ADR-025).

Fake-DB suite: runs without Postgres (also passes with disposable PG).
Production Settings everywhere: the /test/* stack is not under test here.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.auth import Principal, require_principal
from src.api.routes import router
from src.config import Settings, get_settings
from src.services.case_service import get_case_service

ORG_A = "11111111-1111-4111-8111-111111111111"
ORG_B = "22222222-2222-4222-8222-222222222222"


def _production_settings(**kwargs):
    return Settings(app_env="production", database_url="", clerk_secret_key="sk_test_unit", **kwargs)


def _fake_service(row, **methods):
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query, params=None):
            pass

        def fetchone(self):
            return row

    calls: dict = {}

    async def _unused(*args, **kwargs):
        calls["reached"] = True
        raise AssertionError("denied request reached persistence")

    service = SimpleNamespace(_get_db_connection=lambda: SimpleNamespace(cursor=Cursor, close=lambda: None))
    for name, fn in methods.items():
        setattr(service, name, fn)
    service.calls = calls
    return service


def _app(principal, service):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = lambda: _production_settings()
    app.dependency_overrides[require_principal] = lambda: principal
    app.dependency_overrides[get_case_service] = lambda: service
    return app


async def test_cross_org_case_read_denied_before_payload():
    """GET /cases/{id} binds the server org; cross-org reads miss (404), never leak."""
    from fastapi import HTTPException

    async def scoped_detail(case_id, organization_id=None):
        if organization_id != ORG_B:
            raise HTTPException(status_code=404, detail="Case case-1 not found")
        raise AssertionError("cross-org read reached rows")

    service = _fake_service({"organization_id": ORG_B, "driver_id": "driver-b"})
    service.get_case_detail = scoped_detail
    app = _app(Principal("analyst-a", ORG_A, frozenset({"analyst"})), service)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/cases/case-1")
    assert response.status_code == 404


async def test_cross_org_case_change_denied():
    async def claim(*args, **kwargs):
        raise AssertionError("denied change reached persistence")

    service = _fake_service({"organization_id": ORG_B, "driver_id": None})
    service.claim_case_lease = claim
    app = _app(Principal("analyst-a", ORG_A, frozenset({"analyst"})), service)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/cases/case-1/claim", json={"analyst_id": "analyst-a"})
    assert response.status_code == 403


async def test_swapped_driver_id_denied_within_same_org():
    service = _fake_service({"organization_id": ORG_A, "driver_id": "driver-other"})
    app = _app(Principal("p-a", ORG_A, frozenset({"driver"}), "driver-a"), service)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/driver/cases/case-1/session")
    assert response.status_code == 403


async def test_cross_org_sse_denied_before_stream_headers():
    service = _fake_service({"organization_id": ORG_B, "driver_id": None})

    async def stream_case_progress(case_id):
        raise AssertionError("denied SSE reached streamer")

    service.stream_case_progress = stream_case_progress
    app = _app(Principal("analyst-a", ORG_A, frozenset({"analyst"})), service)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/cases/case-1/stream")
    assert response.status_code == 403
    assert "text/event-stream" not in response.headers.get("content-type", "")


async def test_clerk_uuid_org_mismatch_denied():
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query, params=None):
            pass

        def fetchone(self):
            return {"id": "p-a", "organization_id": ORG_B, "roles": ["fraud_analyst"], "driver_id": None}

    service = SimpleNamespace(
        _get_db_connection=lambda: SimpleNamespace(cursor=Cursor, close=lambda: None),
    )

    async def denied_list(**kwargs):
        raise AssertionError("denied request reached list")

    service.list_cases = denied_list
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = lambda: _production_settings()
    app.dependency_overrides[get_case_service] = lambda: service
    payload = {"sub": "user_a", "org_id": ORG_A, "org_role": "org:member"}
    with patch("src.api.auth.authenticate_request", return_value=SimpleNamespace(is_signed_in=True, payload=payload)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/cases", headers={"Authorization": "Bearer signed"})
    assert response.status_code == 403


async def test_persisted_reads_require_server_org_scope():
    from fastapi import HTTPException

    from src.services.case_service import CaseService

    service = CaseService(settings=_production_settings())
    with patch.object(service, "_get_db_connection", return_value=object()):
        with pytest.raises(HTTPException) as exc_info:
            await service.list_cases()
        assert exc_info.value.status_code == 403
        with pytest.raises(HTTPException) as exc_info:
            await service.list_case_history()
        assert exc_info.value.status_code == 403
        with pytest.raises(HTTPException) as exc_info:
            await service.get_case_detail("11111111-1111-4111-8111-111111111111")
        assert exc_info.value.status_code == 403


async def test_list_cases_binds_org_to_count_and_rows():
    seen = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query, params=None):
            seen.append((query, params))

        def fetchone(self):
            return {"count": 0}

        def fetchall(self):
            return []

    from src.services.case_service import CaseService

    service = CaseService(settings=_production_settings())
    with patch.object(service, "_get_db_connection", return_value=SimpleNamespace(cursor=Cursor, close=lambda: None)):
        await service.list_cases(organization_id=ORG_A)
    assert seen, "expected count + row queries"
    selects = [(q, p) for q, p in seen if "SELECT" in q.upper()]
    assert selects, "expected SELECT queries"
    for query, params in selects:
        assert "c.organization_id" in query
        assert ORG_A in params


def test_no_route_accepts_client_organization_id():
    """Server identity propagation: routes take no client org input (exports included)."""
    for route in router.routes:
        param_names = (
            [p.name for p in getattr(route, "dependant", {}).query_params] if hasattr(route, "dependant") else []
        )
        assert "organization_id" not in param_names, f"{route.path} trusts client organization_id"


def test_model_tool_schemas_forbid_org_args():
    from src.services.tool_catalog import model_input_schemas

    for schema in model_input_schemas():
        props = schema.get("properties", {})
        for forbidden in ("organization_id", "actor_id", "roles", "permissions", "runtime_context"):
            assert forbidden not in props, f"{schema.get('title')} exposes {forbidden}"


def test_sync_requires_real_org_and_role():
    from fastapi import HTTPException

    from src.services.access_control import sync_clerk_principal

    for org, role in [(None, "fraud_analyst"), ("org_abc123", "fraud_analyst"), (ORG_A, None)]:
        with pytest.raises(HTTPException) as exc_info:
            sync_clerk_principal(lambda: None, "user_x", org, role, "X")
        assert exc_info.value.status_code == 403


def test_begin_case_agent_turn_missing_org_denied_no_default_collapse():
    """S4-TENANT #294 P0: missing org fails closed, never collapses to a default org."""
    from uuid import uuid4

    from fastapi import HTTPException

    from src.models.schemas import PolicyChatRequest
    from src.services.case_service import CaseService

    service = CaseService(settings=_production_settings())
    req = PolicyChatRequest(query="hello", case_id=uuid4())
    with pytest.raises(HTTPException) as exc_info:
        service._begin_case_agent_turn(req, None, "analyst-a")
    assert exc_info.value.status_code in (403, 503)
    for session in service._agent_sessions.values():
        assert session.get("organization_id") != "018f2f4e-0000-7000-8000-000000000001"


def test_begin_case_agent_turn_missing_org_denied_with_db():
    """Persisted agent-turn path requires server org scope (403, not a default org)."""
    from uuid import uuid4

    from fastapi import HTTPException

    from src.models.schemas import PolicyChatRequest
    from src.services.case_service import CaseService

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query, params=None):
            pass

        def fetchone(self):
            return None

        def fetchall(self):
            return []

    conn = SimpleNamespace(cursor=Cursor, close=lambda: None, commit=lambda: None, rollback=lambda: None)
    service = CaseService(settings=_production_settings())
    req = PolicyChatRequest(query="hello", case_id=uuid4())
    with patch.object(service, "_get_db_connection", return_value=conn):
        with pytest.raises(HTTPException) as exc_info:
            service._begin_case_agent_turn(req, None, "analyst-a")
    assert exc_info.value.status_code == 403


async def test_cross_org_precedent_match_denied_before_service():
    """S4-TENANT #294 P1c: match-precedent pre-checks case scope, then filters by org."""
    from src.services.jev_precedent_service import get_jev_precedent_service

    async def reached(**kwargs):
        raise AssertionError("denied precedent match reached service")

    jev = SimpleNamespace(match_precedent=reached)
    service = _fake_service({"organization_id": ORG_B, "driver_id": None})
    app = _app(Principal("analyst-a", ORG_A, frozenset({"analyst"})), service)
    app.dependency_overrides[get_jev_precedent_service] = lambda: jev
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/cases/case-1/match-precedent", json={"case_id": "case-1", "claim_type": "traffic_gridlock"}
        )
    assert response.status_code == 403


async def test_cross_org_precedent_apply_denied_before_service():
    """S4-TENANT #294 P1c: apply-precedent pre-checks case scope."""
    from src.services.jev_precedent_service import get_jev_precedent_service

    def reached(*args, **kwargs):
        raise AssertionError("denied precedent apply reached service")

    jev = SimpleNamespace(apply_precedent_procedure=reached)
    service = _fake_service({"organization_id": ORG_B, "driver_id": None})
    app = _app(Principal("analyst-a", ORG_A, frozenset({"analyst"})), service)
    app.dependency_overrides[get_jev_precedent_service] = lambda: jev
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/cases/case-1/apply-precedent", json={"precedent_id": "p-1"})
    assert response.status_code == 403


async def test_cross_org_workflow_trace_denied_before_service():
    """S4-TENANT #294 P1c: workflow-trace pre-checks case scope."""
    from src.services.jev_precedent_service import get_jev_precedent_service

    def reached(*args, **kwargs):
        raise AssertionError("denied trace read reached service")

    jev = SimpleNamespace(get_workflow_trace=reached)
    service = _fake_service({"organization_id": ORG_B, "driver_id": None})
    app = _app(Principal("analyst-a", ORG_A, frozenset({"analyst"})), service)
    app.dependency_overrides[get_jev_precedent_service] = lambda: jev
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/cases/case-1/workflow-trace")
    assert response.status_code == 403


async def test_case_writes_require_server_org_scope():
    """claim/record/adjudicate/stream deny persisted writes/reads without server org."""
    from fastapi import HTTPException

    from src.models.schemas import AdjudicationRequest, CaseActionRequest, ClaimCaseRequest
    from src.services.case_service import CaseService

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query, params=None):
            pass

        def fetchone(self):
            return {"id": "row", "version": 1, "status": "ready"}

        def fetchall(self):
            return []

    case_id = "33333333-3333-4333-8333-333333333333"
    service = CaseService(settings=_production_settings())
    conn = SimpleNamespace(cursor=Cursor, close=lambda: None, commit=lambda: None, rollback=lambda: None)
    with patch.object(service, "_get_db_connection", return_value=conn):
        with pytest.raises(HTTPException) as exc_info:
            await service.claim_case_lease(
                case_id, ClaimCaseRequest(analyst_id="analyst-a", role="analyst"), organization_id=None
            )
        assert exc_info.value.status_code == 403
        with pytest.raises(HTTPException) as exc_info:
            await service.record_case_action(
                case_id,
                CaseActionRequest(action_type="REQUEST_EVIDENCE", analyst_id="analyst-a"),
                organization_id=None,
            )
        assert exc_info.value.status_code in (403, 503)
        with pytest.raises(HTTPException) as exc_info:
            await service.adjudicate_case(
                case_id,
                AdjudicationRequest(
                    outcome="DISAGREE",
                    analyst_id="analyst-a",
                    rationale="Evidence confirms dismissal rationale",
                    expected_case_version=1,
                ),
                organization_id=None,
            )
        assert exc_info.value.status_code in (403, 503)
        with pytest.raises(HTTPException) as exc_info:
            async for _ in service.stream_case_progress(case_id, organization_id=None):
                pass
        assert exc_info.value.status_code == 403
