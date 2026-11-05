"""Unit tests for LLM judge gate determinism, strict rubric parsing,
statistical score aggregation, stratified case selection, and conversational response accuracy.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from eval import bench
from src.config import Settings, get_settings
from src.rag.cockpit_agent import CockpitRAGAgent

# ===========================================================================
# 1. Strict Rubric Parsing & Parse Failures
# ===========================================================================


def test_parse_judge_response_valid_json():
    raw = json.dumps({"score": 4, "justification": "Good correctness and grounded."})
    score, just = bench.parse_judge_response(raw)
    assert score == 4
    assert just == "Good correctness and grounded."


def test_parse_judge_response_with_markdown_fences():
    raw = '```json\n{"score": 5, "justification": "Perfect match."}\n```'
    score, just = bench.parse_judge_response(raw)
    assert score == 5
    assert just == "Perfect match."


def test_parse_judge_response_with_text_before_fence():
    raw = 'Here is the evaluation:\n```json\n{"score": 3, "justification": "Partially grounded."}\n```'
    score, just = bench.parse_judge_response(raw)
    assert score == 3
    assert just == "Partially grounded."


@pytest.mark.parametrize(
    "invalid_input",
    [
        "",
        "   ",
        "Not a json",
        '{"score": "five", "justification": "ok"}',
        '{"score": 4.5, "justification": "float"}',
        '{"score": 0, "justification": "zero"}',
        '{"score": 6, "justification": "six"}',
        '{"score": -1, "justification": "negative"}',
        '{"score": true, "justification": "bool"}',
        '{"score": false, "justification": "bool"}',
        '{"score": null, "justification": "null"}',
        '{"justification": "missing score"}',
        '{"score": 4}',  # missing justification
        '{"score": 4, "justification": ""}',  # empty justification
        '{"score": 4, "justification": "   "}',
        "[4, 'Good']",  # list instead of dict
    ],
)
def test_parse_judge_response_rejects_invalid_rubrics(invalid_input):
    with pytest.raises(ValueError):
        bench.parse_judge_response(invalid_input)


def test_score_with_judge_raises_explicit_error_on_parse_failure():
    generate = Mock(return_value=SimpleNamespace(text="unparseable garbage"))
    judge = SimpleNamespace(model_name="gpt-4o-mini", models=SimpleNamespace(generate_content=generate))
    with pytest.raises(ValueError, match="Judge response is not valid JSON"):
        bench._score_with_judge(judge, "Evaluate candidate")


# ===========================================================================
# 2. Judge Determinism & Pinned Configuration
# ===========================================================================


def test_settings_has_pinned_eval_judge_fields():
    settings = Settings(_env_file=None)
    assert hasattr(settings, "eval_judge_model")
    assert hasattr(settings, "eval_judge_temperature")
    assert hasattr(settings, "eval_judge_seed")
    assert settings.eval_judge_model == "gpt-4o-mini"
    assert settings.eval_judge_temperature == 0.0
    assert settings.eval_judge_seed == 42


def test_judge_client_uses_pinned_config_determinism(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "mock-test-key-12345")
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("EVAL_JUDGE_TEMPERATURE", "0.0")
    monkeypatch.setenv("EVAL_JUDGE_SEED", "42")
    get_settings.cache_clear()

    judge = bench._build_judge_client()
    assert judge is not None
    assert judge.model_name == "gpt-4o-mini"
    assert judge.temperature == 0.0
    assert judge.seed == 42


# ===========================================================================
# 3. Stratified Case Selection
# ===========================================================================


def test_select_stratified_cases_preserves_all_when_limit_none():
    cases = [{"id": f"c-{i}", "category": "cat1"} for i in range(20)]
    assert bench.select_stratified_cases(cases, limit=None) == cases
    assert bench.select_stratified_cases(cases, limit=25) == cases


def test_select_stratified_cases_deterministic(tmp_path):
    golden_path = Path("eval/golden_set/rag_testset_100.json")
    if not golden_path.exists():
        pytest.skip("Golden set file missing")
    cases = json.loads(golden_path.read_bytes())

    sel_10_a = bench.select_stratified_cases(cases, limit=10)
    sel_10_b = bench.select_stratified_cases(cases, limit=10)
    assert len(sel_10_a) == 10
    assert [c["id"] for c in sel_10_a] == [c["id"] for c in sel_10_b]

    # Verify coverage of diverse domains in 10-sample selection
    categories_10 = {c["category"] for c in sel_10_a}
    tools_10 = {c.get("expected_tool") for c in sel_10_a}

    assert "conversation" in categories_10
    assert "out_of_scope" in categories_10
    assert None in tools_10  # Zero-tool cases
    assert "search_policy" in tools_10  # Policy tool
    assert any(t in tools_10 for t in ["get_driver_card", "get_driver_trip_history", "check_driver_suspension"])


def test_select_stratified_cases_various_limits():
    golden_path = Path("eval/golden_set/rag_testset_100.json")
    if not golden_path.exists():
        pytest.skip("Golden set file missing")
    cases = json.loads(golden_path.read_bytes())

    for lim in [5, 10, 15, 20, 50]:
        sel = bench.select_stratified_cases(cases, limit=lim)
        assert len(sel) == lim
        # No duplicates
        ids = [c["id"] for c in sel]
        assert len(ids) == len(set(ids))


# ===========================================================================
# 4. Statistical Score Aggregation & Confidence Gate
# ===========================================================================


def test_compute_score_statistics():
    scores = [4, 4, 5, 5, 3, 4, 5, 4, 4, 5]
    stats = bench.compute_score_statistics(scores)
    assert stats["mean"] == 4.3
    assert stats["std"] > 0
    assert stats["sem"] > 0
    assert stats["ci_95_lower"] <= stats["mean"] <= stats["ci_95_upper"]


def test_compute_score_statistics_empty_and_single():
    assert bench.compute_score_statistics([])["mean"] == 0.0
    single = bench.compute_score_statistics([4])
    assert single["mean"] == 4.0
    assert single["std"] == 0.0


# ===========================================================================
# 5. Genuine Bad Answers Fix: Conversational Responses
# ===========================================================================


def test_conversational_agent_answers_accurately():
    agent = CockpitRAGAgent()

    test_queries = [
        "Xin chào, bạn là ai?",
        "Hello, how are you today?",
        "Bạn có thể giúp gì cho tôi?",
        "Trợ lý GreenSM có những chức năng gì?",
        "Chào bạn, hôm nay bạn thế nào?",
        "Who are you and what do you do?",
        "Hi there! What can you help me with on GreenSM?",
        "Cảm ơn bạn nhiều nhé!",
        "Tạm biệt bạn, hẹn gặp lại.",
        "Chúc bạn một ngày làm việc tốt lành!",
    ]

    for question in test_queries:
        resp = agent.execute_turn(question)
        assert resp.raw_tool_data.get("tool_called") is None
        ans_lower = resp.answer.lower()
        assert "greensm" in ans_lower or "trợ lý" in ans_lower
        assert "greensm assistant" in ans_lower


# ===========================================================================
# 6. Driver Tools, Boundary Security and Intent Routing
# ===========================================================================


def test_driver_history_no_mock_fallback_when_db_down():
    from types import SimpleNamespace

    from src.rag.db_tools import get_driver_history

    # Production must never return MOCK_DRIVER_HISTORIES when DB is down
    service_no_db = SimpleNamespace(_get_db_connection=lambda: None)
    res = get_driver_history("drv-8492-nguyen-van-a", service=service_no_db)
    assert res["source"] == "unavailable"
    assert res["found"] is False
    assert res["items"] == []

    # Database query error must also return unavailable and found=False
    def _raise():
        raise RuntimeError("DB connection failure")

    service_err = SimpleNamespace(_get_db_connection=_raise)
    res_err = get_driver_history("drv-8492-nguyen-van-a", service=service_err)
    assert res_err["source"] == "unavailable"
    assert res_err["found"] is False
    assert res_err["items"] == []


def test_driver_profile_loose_substring_matching_rejected():
    from src.rag.db_tools import get_driver_profile

    # 1. Exact plate match (case-insensitive)
    plate_res = get_driver_profile("29E-123.45")
    assert plate_res["found"] is True
    assert plate_res["driver"]["driver_id"] == "drv-8492-nguyen-van-a"
    assert plate_res["driver"]["rating"] == 4.82

    # 2. Exact driver ID match (case-insensitive)
    id_res = get_driver_profile("DRV-8492-NGUYEN-VAN-A")
    assert id_res["found"] is True
    assert id_res["driver"]["driver_id"] == "drv-8492-nguyen-van-a"

    # 3. Exact full name match (accent-stripped containment)
    name_res = get_driver_profile("nguyen van a")
    assert name_res["found"] is True
    assert name_res["driver"]["driver_id"] == "drv-8492-nguyen-van-a"

    # 4. A query containing a short name fragment must NOT match a different driver
    # "an toan" contains "an", but driver "Nguyen Van A" must not be matched by loose containment
    short_frag = get_driver_profile("an toan giao thong")
    assert short_frag["found"] is False

    # A short name fragment from another driver must not match
    no_match = get_driver_profile("nguyen van b")
    assert no_match["found"] is False

    # Short string that happens to be substring of plate or ID in query must not match
    no_plate_substr = get_driver_profile("toi muon tim xe 29E di san bay")
    assert no_plate_substr["found"] is False


def test_license_plate_not_routed_to_related_cases_without_fraud_context():
    agent = CockpitRAGAgent(api_key="test-key")

    # Driver profile/card query containing license plate must route to driver card, NOT check_related_cases_to_vehicle
    tool, args = agent._offline_route("Tra cứu thông tin hồ sơ tài xế Nguyễn Văn A biển số 29E-123.45.")
    assert tool == "get_driver_card"
    assert "29E-123.45" in args.get("driver_identifier", "")

    # Legitimate vehicle-sharing / swapping query routes to check_related_cases_to_vehicle
    tool_related, _ = agent._offline_route("Kiểm tra các vụ việc dùng chung xe biển số 29E-123.45")
    assert tool_related == "check_related_cases_to_vehicle"

    tool_swap, _ = agent._offline_route("Nghi vấn tráo xe biển số 29E-123.45 trong các ca gian lận")
    assert tool_swap == "check_related_cases_to_vehicle"


def test_driver_default_route_to_driver_card_and_db_profile():
    agent = CockpitRAGAgent(api_key="test-key")

    # General driver profile inquiries default to interactive UI get_driver_card
    tool_general, _ = agent._offline_route("Xem thông tin tài xế Nguyễn Văn A")
    assert tool_general == "get_driver_card"

    tool_id, _ = agent._offline_route("Thông tin tài xế drv-8492-nguyen-van-a")
    assert tool_id == "get_driver_card"

    # Explicit database credential queries route to get_driver_profile
    tool_db, _ = agent._offline_route("Retrieve driver profile from db for drv-8492-nguyen-van-a")
    assert tool_db == "get_driver_profile"

    tool_db2, _ = agent._offline_route("Show credential standing for drv-8492 from database")
    assert tool_db2 == "get_driver_profile"


def test_bench_stratified_ten_case_offline_matches():
    golden_path = Path("eval/golden_set/rag_testset_100.json")
    if not golden_path.exists():
        pytest.skip("Golden set file not found")

    test_cases = json.loads(golden_path.read_bytes())
    selected_10 = bench.select_stratified_cases(test_cases, 10)
    assert len(selected_10) == 10

    agent = CockpitRAGAgent(api_key="test-key")
    equiv_driver = {"get_driver_card", "get_driver_profile", "check_driver_suspension"}

    for tc in selected_10:
        resp = agent.execute_turn(tc["question"])
        tool = resp.tool_called or resp.raw_tool_data.get("tool_called")
        expected = tc.get("expected_tool")

        if expected is None:
            assert tool is None, f"Expected None for {tc['id']}, got {tool}"
        elif expected == "search_policy":
            assert tool in ("search_policy", "search_policy_documents"), f"Failed for {tc['id']}: {tool}"
        elif expected in equiv_driver:
            assert tool in equiv_driver, f"Failed for {tc['id']}: {tool}"
        else:
            assert tool == expected, f"Failed for {tc['id']}: {tool}"
