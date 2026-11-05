import json

from eval.grounding_benchmark import load_dpo_pairs, run_benchmark


def test_dpo_pairs_have_required_fields():
    assert load_dpo_pairs()


def test_report_has_issue_199_gates(tmp_path):
    golden = tmp_path / "gold.json"
    golden.write_text(
        json.dumps(
            [{"id": "x", "question": "Điều 12.2", "gold_answer": "Điều 12.2", "expected_articles": ["Điều 12.2"]}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    report = run_benchmark(golden, tmp_path / "report.json")
    assert report["policy_retrieval_precision_pct"] == 100.0
    assert report["grounding_errors"] == 0
    assert report["cases"][0]["confidence_tier"] == "high"
    assert report["acceptance"]["case_results_complete"] is True
    assert report["human_verification"]["status"] == "pending_human_review"


def test_benchmark_reports_non_applicable_cases_and_extra_citations(tmp_path):
    golden = tmp_path / "gold.json"
    golden.write_text(
        json.dumps(
            [
                {"id": "empty", "question": "hello"},
                {
                    "id": "extra",
                    "question": "Điều 12.2",
                    "gold_answer": "Điều 12.2",
                    "expected_articles": ["Điều 12.2"],
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    report = run_benchmark(golden, tmp_path / "report.json")
    assert report["not_applicable_cases"] == 1
    assert report["evaluated_cases"] == 1
    assert len(report["cases"]) == 2
