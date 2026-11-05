import sys

from src.services import agent_tracing


def test_trace_identity_contains_correlations_but_not_case_identifier():
    identity = agent_tracing.make_trace_identity(
        case_id="sensitive-case-identifier",
        run_id="run-1",
        request_id="request-1",
        environment="test",
        model="gemini-test",
        prompt_version="prompt-v1",
    )
    metadata = agent_tracing._trace_metadata(identity)
    assert metadata["trace_id"] == identity["trace_id"]
    assert metadata["gen_ai.request.model"] == "gemini-test"
    assert "sensitive-case-identifier" not in str(metadata)


def test_trace_scope_fails_open_when_provider_is_unavailable(monkeypatch):
    monkeypatch.setattr(agent_tracing, "_enabled", lambda: True)
    monkeypatch.setitem(sys.modules, "langsmith", None)
    with agent_tracing.trace_turn({"trace_id": "trace-1"}) as run:
        assert run is None
