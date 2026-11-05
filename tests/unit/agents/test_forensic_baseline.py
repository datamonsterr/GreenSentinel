"""Contract rejection and label isolation checks for the offline baseline."""

import json
import unittest

from pydantic import ValidationError

from src.agents.forensic_baseline import assess_case
from src.models.forensic import ForensicInput, ForensicOutput
from tests.support.repo import REPO_ROOT


class TestForensicBaseline(unittest.TestCase):
    def setUp(self) -> None:
        path = REPO_ROOT / "eval/golden_set/forensic_mock_cases.json"
        self.facts = json.loads(path.read_text(encoding="utf-8"))[0]["input"]

    def test_rejects_labels_and_invalid_measurements(self) -> None:
        for change in (
            {"scenario": "gps_spoofing"},
            {"telemetry_points": -1},
            {"stationary_duration_s": float("nan")},
            {"platform_outage": "false"},
        ):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                ForensicInput.model_validate(self.facts | change)

    def test_identifier_does_not_change_assessment(self) -> None:
        first = assess_case(ForensicInput.model_validate(self.facts))
        second = assess_case(ForensicInput.model_validate(self.facts | {"case_id": "gps_spoofing"}))
        self.assertEqual(first.model_dump(exclude={"case_id"}), second.model_dump(exclude={"case_id"}))

    def test_output_rejects_invalid_confidence_and_empty_evidence(self) -> None:
        output = assess_case(ForensicInput.model_validate(self.facts)).model_dump()
        for change in ({"confidence": 1.1}, {"confidence": float("nan")}, {"evidence": []}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                ForensicOutput.model_validate(output | change)

    def test_benchmark_core_cases_no_regression(self) -> None:
        path = REPO_ROOT / "eval/golden_set/forensic_mock_cases.json"
        cases = json.loads(path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(cases), 10)
        for entry in cases:
            case = ForensicInput.model_validate(entry["input"])
            output = assess_case(case)
            self.assertEqual(output.category, entry["expected_category"])
            grounded = {e.source for e in output.evidence}
            for req in entry["required_evidence"]:
                self.assertIn(req, grounded)
