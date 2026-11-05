# Evaluation corpus v1

`corpus.json` is the shared evaluation index for issue #64. It references existing fixtures instead of duplicating runtime evidence. `expected`, split metadata, SME review and follow-up fields are evaluation-only and must never enter model, tool or runtime inputs.

## Contents

- 30 held-out PRD protocol cases: 10 DIC, 10 traffic false alarms and 10 technical outages.
- Separate ERR-01 through ERR-05 taxonomy coverage.
- RAG, tool, forensic brief, role/error and driver/A2A cases linked to repository fixtures.
- Explicit train, tuning and held-out splits with leakage groups.
- Source/version provenance, expected facts, allowed uncertainty, policy references, guardrail/action expectations and SME status for every case.

All labels currently have `sme_review.status = pending`. They are engineering expectations derived from versioned requirements, not approved production truth.

## Deterministic commands

```bash
python -m eval.generate_evaluation_corpus
python -m eval.evaluation_corpus validate
python -m eval.evaluation_corpus analyze \
  --results eval/corpus/v1/inventory_results.json \
  --json-output eval/results/issue64_error_analysis.json \
  --markdown-output eval/results/issue64_error_analysis.md
pytest tests/test_evaluation_corpus.py -q
```

The committed inventory run is a repository-artifact review. Missing case results are reported as `not_run`; they are not converted into fabricated measurements. Replace it with a version-pinned fixture, isolated-database or hosted run and record the environment in the result file.
