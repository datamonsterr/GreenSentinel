"""Run with python -m eval.reasoning_baseline. No network or database required."""

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from src.agents.forensic_baseline import BASELINE_VERSION, assess_case
from src.models.forensic import ForensicInput, ForensicOutput

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    dataset = ROOT / "eval/golden_set/forensic_mock_cases.json"
    raw = dataset.read_bytes().replace(b"\r\n", b"\n")
    cases = json.loads(raw)
    if not cases:
        raise ValueError("Benchmark requires at least one case.")
    schema = ForensicOutput.model_json_schema()
    validator = Draft202012Validator(schema)
    outputs, scores = [], []
    for entry in cases:
        case = ForensicInput.model_validate(entry["input"])
        output = assess_case(case).model_dump(mode="json")
        facts = case.model_dump()
        evidence = output["evidence"]
        required = set(entry["required_evidence"])
        grounded = {
            item["source"]
            for item in evidence
            if item["source"] in facts
            and type(item["value"]) is type(facts[item["source"]])
            and item["value"] == facts[item["source"]]
        }
        outputs.append(output)
        scores.append(
            {
                "case_id": case.case_id,
                "expected_category": entry["expected_category"],
                "predicted_category": output["category"],
                "category_accuracy": float(output["category"] == entry["expected_category"]),
                "schema_validity": float(validator.is_valid(output)),
                "evidence_grounding": sum(item["source"] in grounded for item in evidence) / len(evidence),
                "required_evidence_recall": len(required & grounded) / len(required) if required else 1.0,
            }
        )
    metrics = ("category_accuracy", "schema_validity", "evidence_grounding", "required_evidence_recall")
    report = {
        "baseline_version": BASELINE_VERSION,
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "case_count": len(cases),
        "scope": "Synthetic development smoke benchmark; not held-out or production accuracy.",
        "confidence_semantics": "Fixed uncalibrated rule support; 0 means abstention.",
        "metrics": {key: sum(row[key] for row in scores) / len(scores) for key in metrics},
        "cases": scores,
    }
    destination = ROOT / "eval/results"
    destination.mkdir(parents=True, exist_ok=True)
    for name, data in (
        ("reasoning_baseline.json", report),
        ("forensic_outputs.json", outputs),
        ("forensic_output.schema.json", schema),
    ):
        (destination / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2))
    if any(value < 1.0 for value in report["metrics"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
