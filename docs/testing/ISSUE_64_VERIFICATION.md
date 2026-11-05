# Issue #64 verification — versioned evaluation corpus

## Scope and environment

- Branch: `son/s2-f07-eval-corpus`
- Branch base revision: `05c685e45431ea9ef6f5c54382b18295ac6df943`
- Corpus source revision: `16c1ad6bdc910badbe852418bc5de5b456759156`
- Environment: Windows, Python 3.14.8 with temporary workspace-local `jsonschema 4.26.0`, `pytest 9.1.1` and Ruff 0.16.10.
- Evidence class: local schema/contract verification and repository-artifact inventory only. No isolated database, model-provider, hosted or three-reviewer UAT run is claimed.

## Definition of Done evidence

| DoD item | Evidence | Status |
|---|---|---|
| PRD 30-case protocol plus shared flow cases | [`corpus.json`](../../eval/corpus/v1/corpus.json) contains 10 DIC, 10 traffic false alarms, 10 technical outages and 23 separate taxonomy/RAG/tool/brief/role/driver cases. | Implemented |
| Provenance, facts, uncertainty, policy, guardrail/action and SME state | Enforced by [`corpus.schema.json`](../../eval/corpus/v1/corpus.schema.json). All 53 records declare these fields. All SME labels remain explicitly `pending`; no approval is inferred. | Implemented; SME approval pending |
| Leakage-safe splits and separate ERR taxonomy | Validator reports train 8, tuning 8 and held-out 37. All 30 protocol cases are held out. `ERR-01` through `ERR-05` use the separate `taxonomy_classifier` suite. | Implemented |
| Deterministic validation and error analysis | [`evaluation_corpus.py`](../../eval/evaluation_corpus.py), five contract tests and generated [error analysis](../../eval/results/issue64_error_analysis.md). The inventory detects the stale legacy `AUTO_DISMISS` gold label by stable case ID. | Implemented |
| PR, worklog and journal traceability | [Daily worklog](../worklog/2026-10-02.md) and [journal](../journal/JOURNAL.md) identify Phạm Thanh Sơn and issue #64. PR/CI links must be added after publication. | Branch evidence complete; PR/CI pending |

## Commands and observed results

```text
python -m eval.generate_evaluation_corpus
# wrote 53 cases to eval/corpus/v1/corpus.json

python -m unittest tests.test_evaluation_corpus -v
# Ran 5 tests in 0.139s — OK

python -m eval.evaluation_corpus validate
# 53 cases; held_out=37, train=8, tuning=8; SME pending=53
# operational suites: DIC=10, traffic=10, outage=10

ruff check eval/evaluation_corpus.py eval/generate_evaluation_corpus.py tests/test_evaluation_corpus.py
# All checks passed

ruff format --check eval/evaluation_corpus.py eval/generate_evaluation_corpus.py tests/test_evaluation_corpus.py
# 3 files already formatted
```

## Error-analysis boundary

The committed inventory result is not a model benchmark. It records one observed repository inconsistency: `driver-a2a-traffic` inherits a legacy fixture that expects `AUTO_DISMISS`, while PRD FR-03 requires analyst-confirmed dismissal. The other 52 records are `not_run`, not failures or fabricated measurements. Run them against version-pinned fixture, isolated-database or hosted environments before reporting decision accuracy, MTTR or guardrail adherence.

## Remaining acceptance work

1. Obtain independent fraud-operations SME review and update each record from `pending` only with reviewer identity and timestamp.
2. Execute the 30 held-out cases with three independent reviewers for PRD §9.3 MTTR/concordance evidence.
3. Publish the branch, open a PR with `Refs #64`, and attach CI/hosted evidence. Do not use `Closes #64` until the full DoD is accepted.
