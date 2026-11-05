"""Integration tests for GET / DELETE /api/v1/cases/{id}/agent-context and attachment validation."""

import base64
from typing import Any
from uuid import uuid4

import pytest
from dotenv import load_dotenv
from google.genai import types
from httpx import ASGITransport, AsyncClient

from src.api.auth import Principal, require_principal
from src.config import get_settings
from src.main import app
from src.services.agent_runtime import _begin, _connection, _finish
from src.services.chat_event_writer import ChatEventWriter

CASE = "018f2f4e-a000-7000-8000-000000000001"
OWNER = "018f2f4e-1000-7000-8000-000000000001"
ANALYST_2 = "018f2f4e-1000-7000-8000-000000000002"
ORG = "018f2f4e-0000-7000-8000-000000000001"
OTHER_ORG = "018f2f4e-0000-7000-8000-000000000002"


def _is_db_available() -> bool:
    try:
        with _connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM app.fraud_cases LIMIT 1;")
            return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_agent_context_auth_and_scoping():
    if not _is_db_available():
        pytest.skip("PostgreSQL database not available")

    # 1. Unauthenticated -> 401
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        res = await c.get(f"/api/v1/cases/{CASE}/agent-context")
        assert res.status_code == 401

    # 2. Driver role -> 403
    app.dependency_overrides[require_principal] = lambda: Principal(
        "018f2f4e-1000-7000-8000-000000000003", ORG, frozenset({"driver"}), driver_id="drv-1"
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            res = await c.get(f"/api/v1/cases/{CASE}/agent-context")
            assert res.status_code == 403
    finally:
        app.dependency_overrides.pop(require_principal, None)

    # 3. Wrong organization scope -> 403
    app.dependency_overrides[require_principal] = lambda: Principal(OWNER, OTHER_ORG, frozenset({"analyst"}))
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            res = await c.get(f"/api/v1/cases/{CASE}/agent-context")
            assert res.status_code in {403, 404}
    finally:
        app.dependency_overrides.pop(require_principal, None)


@pytest.mark.asyncio
async def test_get_agent_context_returns_usage_and_turn_count():
    if not _is_db_available():
        pytest.skip("PostgreSQL database not available")

    actor = Principal(OWNER, ORG, frozenset({"analyst"}))
    app.dependency_overrides[require_principal] = lambda: actor

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            res = await c.get(f"/api/v1/cases/{CASE}/agent-context")
            assert res.status_code == 200
            data = res.json()
            assert "prompt_tokens" in data
            assert "completion_tokens" in data
            assert "total_tokens" in data
            assert "context_window" in data
            assert data["context_window"] == 1_048_576
            assert "breakdown" in data
            assert "turn_count" in data
            assert isinstance(data["turn_count"], int)
    finally:
        app.dependency_overrides.pop(require_principal, None)


@pytest.mark.asyncio
async def test_delete_agent_context_isolated_to_caller():
    if not _is_db_available():
        pytest.skip("PostgreSQL database not available")

    actor1 = Principal(OWNER, ORG, frozenset({"analyst"}))
    actor2 = Principal(ANALYST_2, ORG, frozenset({"analyst", "senior_analyst"}))

    # Seed 1 turn for actor1 and 1 turn for actor2
    t1_id = f"test-turn-a1-{uuid4()}"
    t2_id = f"test-turn-a2-{uuid4()}"

    row1, fresh1 = _begin(actor1, CASE, t1_id, "Query A1")
    w1 = ChatEventWriter(
        request_id=str(uuid4()),
        case_id=CASE,
        session_id=str(row1["session_id"]),
        turn_id=t1_id,
        run_id=str(row1["run_id"]),
    )
    w1.complete()
    _finish(row1["run_id"], w1, "Answer A1", "completed")

    row2, fresh2 = _begin(actor2, CASE, t2_id, "Query A2")
    w2 = ChatEventWriter(
        request_id=str(uuid4()),
        case_id=CASE,
        session_id=str(row2["session_id"]),
        turn_id=t2_id,
        run_id=str(row2["run_id"]),
    )
    w2.complete()
    _finish(row2["run_id"], w2, "Answer A2", "completed")

    app.dependency_overrides[require_principal] = lambda: actor1

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            # Delete actor1's context
            del_res = await c.delete(f"/api/v1/cases/{CASE}/agent-context")
            assert del_res.status_code == 200
            del_data = del_res.json()
            assert "deleted_turns" in del_data
            assert "deleted_messages" in del_data
            assert del_data["deleted_turns"] >= 1

            # Check that actor1's turns are gone
            with _connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) AS cnt FROM app.agent_runtime_turns WHERE case_id=%s::uuid AND actor_id=%s::uuid",
                    (CASE, actor1.id),
                )
                assert cur.fetchone()["cnt"] == 0

                # Crucial scoping invariant: actor2's turns for that case are untouched!
                cur.execute(
                    "SELECT count(*) AS cnt FROM app.agent_runtime_turns WHERE case_id=%s::uuid AND actor_id=%s::uuid",
                    (CASE, actor2.id),
                )
                assert cur.fetchone()["cnt"] >= 1

                # Verify audit event "context_cleared" was written
                cur.execute(
                    "SELECT * FROM app.audit_events WHERE case_id=%s::uuid AND action='context_cleared' ORDER BY sequence DESC LIMIT 1",
                    (CASE,),
                )
                audit_row = cur.fetchone()
                assert audit_row is not None
                assert audit_row["action"] == "context_cleared"
                assert audit_row["result"] == "accepted"
    finally:
        app.dependency_overrides.pop(require_principal, None)


@pytest.mark.asyncio
async def test_case_agent_messages_append_only_trigger_and_non_superuser_clear():
    if not _is_db_available():
        pytest.skip("PostgreSQL database not available")

    import psycopg.errors

    with _connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM app.case_agent_sessions WHERE case_id = %s::uuid", (CASE,))
        row = cur.fetchone()
        if row:
            session_id = row["id"]
        else:
            cur.execute(
                "INSERT INTO app.case_agent_sessions (id, case_id) VALUES (gen_random_uuid(), %s::uuid) RETURNING id",
                (CASE,),
            )
            session_id = cur.fetchone()["id"]
        test_turn_id = str(uuid4())

        cur.execute(
            """INSERT INTO app.case_agent_messages (session_id, turn_id, role, content)
               VALUES (%s, %s::uuid, 'user', 'Tin nhắn thử nghiệm')
               RETURNING id""",
            (session_id, test_turn_id),
        )
        msg_id = cur.fetchone()["id"]
        conn.commit()

    # 1. Plain DELETE without app.agent_context_clear still raises 55000
    with _connection() as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState) as exc_info:
            cur.execute("DELETE FROM app.case_agent_messages WHERE id = %s", (msg_id,))
        assert "append-only" in str(exc_info.value)
        conn.rollback()

    # 2. UPDATE always raises 55000 even with app.agent_context_clear = 'on'
    with _connection() as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL app.agent_context_clear = 'on';")
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState) as exc_info:
            cur.execute("UPDATE app.case_agent_messages SET content = 'Sửa' WHERE id = %s", (msg_id,))
        assert "append-only" in str(exc_info.value)
        conn.rollback()

    # 3. Non-superuser role verification:
    role_name = f"test_role_{uuid4().hex[:8]}"
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(f"CREATE ROLE {role_name} NOLOGIN;")
        cur.execute(f"GRANT USAGE ON SCHEMA app TO {role_name};")
        cur.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO {role_name};")
        cur.execute(f"GRANT ALL ON ALL SEQUENCES IN SCHEMA app TO {role_name};")
        conn.commit()

    try:
        with _connection() as conn, conn.cursor() as cur:
            cur.execute(f"SET ROLE {role_name};")
            # a) Confirm that SET LOCAL session_replication_role = 'replica' FAILS for non-superuser
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("SET LOCAL session_replication_role = 'replica';")
            conn.rollback()

        with _connection() as conn, conn.cursor() as cur:
            cur.execute(f"SET ROLE {role_name};")
            # b) Confirm that plain DELETE still raises for non-superuser
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState) as exc_info:
                cur.execute("DELETE FROM app.case_agent_messages WHERE id = %s", (msg_id,))
            assert "append-only" in str(exc_info.value)
            conn.rollback()

        with _connection() as conn, conn.cursor() as cur:
            cur.execute(f"SET ROLE {role_name};")
            # c) SET LOCAL app.agent_context_clear = 'on' SUCCEEDS for non-superuser and allows deletion
            cur.execute("SET LOCAL app.agent_context_clear = 'on';")
            cur.execute("DELETE FROM app.case_agent_messages WHERE id = %s", (msg_id,))
            assert cur.rowcount == 1
            conn.commit()
    finally:
        with _connection() as conn, conn.cursor() as cur:
            cur.execute(f"DROP OWNED BY {role_name}; DROP ROLE IF EXISTS {role_name};")
            conn.commit()


@pytest.mark.asyncio
async def test_policy_chat_attachments_forwarded_to_model(monkeypatch):
    if not _is_db_available():
        pytest.skip("PostgreSQL database not available")

    load_dotenv(".env", override=False)
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-provider-key")
    get_settings.cache_clear()

    actor = Principal(OWNER, ORG, frozenset({"analyst"}))
    app.dependency_overrides[require_principal] = lambda: actor

    received_parts = []

    async def mock_generate_content(*args: Any, **kwargs: Any) -> Any:
        contents = kwargs.get("contents") or (args[1] if len(args) > 1 else [])
        for c in contents:
            for p in getattr(c, "parts", []):
                received_parts.append(p)

        return types.GenerateContentResponse(
            candidates=[
                types.Candidate(content=types.Content(role="model", parts=[types.Part.from_text(text="Ảnh đã xử lý.")]))
            ]
        )

    monkeypatch.setattr("google.genai.models.AsyncModels.generate_content", mock_generate_content)

    img_raw = b"test-image-binary-content"
    img_b64 = base64.b64encode(img_raw).decode("ascii")

    payload = {
        "query": "Kiểm tra ảnh đính kèm",
        "case_id": CASE,
        "turn_id": str(uuid4()),
        "event_schema_version": "1.1",
        "attachments": [{"name": "meter.png", "media_type": "image/png", "data_base64": img_b64}],
    }

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            # 1. Valid attachment is forwarded as inline image part
            res = await c.post("/api/v1/policy/chat/stream", json=payload)
            assert res.status_code == 200

            # Verify received parts contain the inline data image part
            has_image_part = any(
                getattr(p, "inline_data", None) and p.inline_data.mime_type == "image/png" for p in received_parts
            )
            assert has_image_part

            # 2. Reject non-image attachment with 422
            bad_mime = {
                **payload,
                "attachments": [{"name": "bad.pdf", "media_type": "application/pdf", "data_base64": img_b64}],
            }
            res_bad = await c.post("/api/v1/policy/chat/stream", json=bad_mime)
            assert res_bad.status_code == 422

            # 3. Reject > 3 attachments with 422
            too_many = {
                **payload,
                "attachments": [
                    {"name": f"img_{i}.png", "media_type": "image/png", "data_base64": img_b64} for i in range(4)
                ],
            }
            res_many = await c.post("/api/v1/policy/chat/stream", json=too_many)
            assert res_many.status_code == 422
    finally:
        app.dependency_overrides.pop(require_principal, None)
        get_settings.cache_clear()
