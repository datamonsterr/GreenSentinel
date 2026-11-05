import json

import pytest

from eval.agent_conversation_benchmark import (
    TurnResult,
    aggregate_case_state,
    load_scenarios,
    parse_sse,
    run_scenario,
    score_scenario,
    tool_records,
)
from tests.support.repo import REPO_ROOT

GOLD = REPO_ROOT / "eval/golden_set/agent_conversations_v1.json"


def test_golden_set_has_long_seeded_scenarios_and_heldout_gold():
    scenarios = load_scenarios(GOLD)
    assert len(scenarios) >= 13
    assert all(len(s["turns"]) >= 12 for s in scenarios)
    assert {s["label"] for s in scenarios} >= {"ERR02 DIC", "ERR05 fakegps", "prompt injection"}
    assert all("gold" in s and "required_tools" in s["gold"] for s in scenarios)


def test_parse_sse_accepts_multiline_json_and_event_name():
    events = parse_sse(
        'event: tool\ndata: {"name":"get_case_context",\ndata: "status":"ok"}\n\nevent: done\ndata: {"status":"complete"}\n'
    )
    assert events == [
        {"name": "get_case_context", "status": "ok", "event": "tool"},
        {"status": "complete", "event": "done"},
    ]


def test_run_scenario_posts_contract_payload_at_http_boundary():
    seen = []

    def fake_post(base, case, query, turn, token, timeout):
        seen.append((base, case, query, turn, token, timeout))
        return 200, 'event: tool\ndata: {"tool":"get_case_context"}\n\nevent: done\ndata: {"text":"Đã xong"}\n', 12.5

    scenario = load_scenarios(GOLD)[0]
    result = run_scenario(scenario, base_url="https://isolated.example", token="test-token", post=fake_post)
    assert len(seen) == len(scenario["turns"])
    assert seen[0][1:5] == (scenario["case_id"], scenario["turns"][0], "err02-dic-t01", "test-token")
    assert result["turns"] == 12 and result["latency_ms"]["p50"] == 12.5


def test_score_does_not_turn_answer_keywords_into_terminal_success():
    scenario = load_scenarios(GOLD)[0]
    rows = [TurnResult("t", 200, 1, [{"tool": "get_case_context"}], "Đã hoàn tất")]
    result = score_scenario(scenario, rows)
    assert result["terminal_outcome"] is None
    assert result["terminal_matches_api_state"] is False


def test_tool_pairing_preserves_repeated_ids_and_sequence():
    events = [
        {"event": "tool.start", "data": {"tool_call_id": "a", "name": "ask_interactive_question"}},
        {"event": "tool.end", "data": {"tool_call_id": "a", "status": "ok"}},
        {"event": "tool.start", "data": {"tool_call_id": "b", "name": "ask_interactive_question"}},
        {"event": "tool.end", "data": {"tool_call_id": "b", "status": "declined"}},
    ]
    assert [r["tool_call_id"] for r in tool_records(events)] == ["a", "b"]
    assert [r["end_sequence"] for r in tool_records(events)] == [1, 3]


def test_run_scenario_routes_existing_question_to_scripted_respondent():
    seen = []

    def fake_post(*args):
        return 200, 'event: workflow.question\ndata: {"kind":"question","question_id":"q1"}\n\n', 1

    scenario = load_scenarios(GOLD)[0]
    run_scenario(scenario, base_url="https://isolated.example", token="t", post=fake_post, respondent=seen.append)
    assert seen[0]["question"]["question_id"] == "q1"


def test_terminal_run_completed_and_live_api_state_gate_gold():
    scenario = load_scenarios(GOLD)[0]
    rows = [TurnResult("t", 200, 1, [{"event": "run.completed", "data": {"status": "complete"}}], "Đã hoàn tất")]
    assert score_scenario(scenario, rows)["terminal_event"]["event"] == "run.completed"
    assert not score_scenario(scenario, rows)["terminal_matches_api_state"]
    scenario["gold"]["requires_terminal_proof"] = True
    state = {"live": True, "terminal_outcome": scenario["gold"]["terminal"], "terminal_artifact_id": "m1"}
    assert score_scenario(scenario, rows, state)["terminal_matches_api_state"]


def test_fixture_state_cannot_be_promoted_to_live():
    with pytest.raises(ValueError, match="live API"):
        aggregate_case_state("case", lambda _: {"live": False, "terminal_outcome": "review_complete"})


def test_score_requires_api_state_for_signoff_delivery_and_traces():
    scenario = next(s for s in load_scenarios(GOLD) if s["id"] == "duplicate-send")
    scenario["gold"]["requires_terminal_proof"] = True
    rows = [TurnResult("t", 200, 1, [{"tool": "get_action_status"}], "đã gửi", ["ls-1"])]
    result = score_scenario(
        scenario,
        rows,
        {
            "live": True,
            "terminal_outcome": "already_delivered",
            "terminal_artifact_id": "m1",
            "human_signoff": True,
            "delivery": "duplicate_prevented",
            "duplicate_result": "prevented",
        },
    )
    assert result["terminal_matches_api_state"] is True
    assert result["human_signoff"] is True and result["duplicate_result"] == "prevented"
    assert result["langsmith_trace_refs"] == ["ls-1"]


def test_schema_rejects_short_conversation(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "scenarios": [{"id": "x", "case_id": "x", "turns": ["one"], "gold": {"required_tools": ["x"]}}],
            }
        )
    )
    with pytest.raises(ValueError, match="invalid or duplicate|12 turns"):
        load_scenarios(p)
