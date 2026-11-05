"""Contract tests for the versioned, label-isolated evaluation corpus."""

import copy
import json
import unittest
from pathlib import Path

from eval.evaluation_corpus import analyze_results, load_json, render_markdown, validate_corpus
from eval.generate_evaluation_corpus import build_corpus

ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = ROOT / "eval/corpus/v1/corpus.json"
SCHEMA_PATH = ROOT / "eval/corpus/v1/corpus.schema.json"


class TestEvaluationCorpus(unittest.TestCase):
    def setUp(self) -> None:
        self.corpus = load_json(CORPUS_PATH)
        self.schema = load_json(SCHEMA_PATH)

    def test_generated_artifact_is_current_and_valid(self) -> None:
        self.assertEqual(self.corpus, build_corpus())
        summary = validate_corpus(self.corpus, self.schema)
        self.assertEqual(summary["case_count"], 53)
        self.assertEqual(summary["suite_counts"]["operational_dic"], 10)
        self.assertEqual(summary["suite_counts"]["operational_traffic_false_alarm"], 10)
        self.assertEqual(summary["suite_counts"]["operational_technical_outage"], 10)
        self.assertEqual(summary["sme_review_counts"], {"pending": 53})

    def test_protocol_is_held_out_and_taxonomy_is_separate(self) -> None:
        protocol = [case for case in self.corpus["cases"] if case["suite"].startswith("operational_")]
        taxonomy = [case for case in self.corpus["cases"] if case["suite"] == "taxonomy_classifier"]
        self.assertEqual(len(protocol), 30)
        self.assertEqual({case["split"] for case in protocol}, {"held_out"})
        self.assertEqual(
            {fact["value"] for case in taxonomy for fact in case["expected"]["facts"] if fact["key"] == "category"},
            {"ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05"},
        )

    def test_no_case_allows_automatic_punitive_or_dismissal_action(self) -> None:
        for case in self.corpus["cases"]:
            with self.subTest(case_id=case["case_id"]):
                action = case["expected"]["action"]
                self.assertFalse(action["punitive"])
                self.assertNotIn(action["expected"].lower(), {"auto_dismiss", "automatic_dismissal"})
                if "dismiss" in action["expected"]:
                    self.assertTrue(action["human_confirmation_required"])

    def test_rejects_label_leakage_and_cross_split_groups(self) -> None:
        leaked = copy.deepcopy(self.corpus)
        leaked["cases"][0]["execution"]["input"]["expected_category"] = "ERR-02"
        with self.assertRaisesRegex(ValueError, "leaks evaluation labels"):
            validate_corpus(leaked, self.schema)

        crossed = copy.deepcopy(self.corpus)
        other_split = next(case for case in crossed["cases"] if case["split"] != crossed["cases"][0]["split"])
        other_split["leakage_group"] = crossed["cases"][0]["leakage_group"]
        with self.assertRaisesRegex(ValueError, "leakage groups cross splits"):
            validate_corpus(crossed, self.schema)

        invalid_review = copy.deepcopy(self.corpus)
        invalid_review["cases"][0]["sme_review"].update(
            {"status": "approved", "reviewer": "reviewer@example.com", "reviewed_at": "not-a-date"}
        )
        with self.assertRaisesRegex(ValueError, "schema validation failed"):
            validate_corpus(invalid_review, self.schema)

    def test_error_analysis_maps_failures_and_missing_cases(self) -> None:
        run = json.loads((ROOT / "eval/corpus/v1/inventory_results.json").read_text(encoding="utf-8"))
        analysis = analyze_results(self.corpus, run)
        self.assertEqual(analysis["status_counts"], {"fail": 1, "not_run": 52})
        self.assertEqual(len(analysis["coverage_gaps"]), 52)
        self.assertEqual(len(analysis["findings"]), 1)
        self.assertEqual(len(analysis["follow_ups"]), 1)
        stale = next(item for item in analysis["findings"] if item["case_id"] == "driver-a2a-traffic")
        self.assertEqual(stale["owner_layer"], "policy")
        self.assertIn("AUTO_DISMISS", stale["failures"][0])
        report = render_markdown(analysis)
        self.assertIn("`driver-a2a-traffic`", report)
        self.assertIn("Remove stale AUTO_DISMISS evaluation labels", report)


if __name__ == "__main__":
    unittest.main()
