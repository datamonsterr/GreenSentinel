# Issue #62 verification: grounded advisory reasoning

## Scope and authorization

Owner: Trân (@trantran2929), assisted by Codex and bounded implementation workers. The user's chat on 2026-10-03 explicitly authorizes bypassing #64's gate, using that branch's evaluation artifacts, and the local acceptance thresholds recorded in [ADR-014](../architecture/adr-014-grounded-advisory-evaluation.md). This does not accept or close #64.

Baseline inspected: [PR #40](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/pull/40), merge `586caec05ddb7626a1f47066b55154e74d245cc0`, and the existing standalone `forensic-rules-v1` baseline. PRD FR-06 and the ERR-02/ERR-05 Phase 1 scope remain controlling. Automatic dismissal, sanctions, and deferred ERR-03/04 product flows are excluded.

The existing draft contained unsupported clause names and calibration claims. Its benchmark manufactured runtime observations from evaluation suite names. Those are replaced by source-backed versioned citations and explicit executable-input boundaries.

## Evidence mapping

| Requirement | Evidence | Boundary |
|---|---|---|
| Structured advisory output and score semantics | [Model contract](../../src/models/forensic.py), [classifier](../../src/agents/forensic_baseline.py) | Uncalibrated ordinal support, never similarity or violation probability |
| Versioned policy grounding and abstention | [Policy repository/Q&A](../../src/services/grounded_policy.py), [runtime policy executor](../../src/services/tool_execution.py), [classifier tests](../../tests/test_agents/test_grounded_classifier.py), [runtime tests](../../tests/test_services/test_versioned_policy_retrieval.py) | Exact source text; missing or conflicting sources fail closed |
| Reproducible paired evaluation | [Benchmark](../../eval/benchmark_classifier.py), [benchmark tests](../../tests/test_classifier_benchmark.py) | Fixture/local; unsupported evidence adapters explicitly not run |
| Frozen thresholds and human confirmation | [ADR-014](../architecture/adr-014-grounded-advisory-evaluation.md) | Approved before session tuning; no automated sanctions |
| Attribution and validation | This record, issue-linked PR, worklog and journal | No inferred SME or hosted acceptance |

## Environment and commands

Environment: Windows, root workspace virtual environment, Python 3.11.16, pytest 9.1.1, Ruff 0.16.8. The isolated worktree is `.worktrees/issue-62`, branch `feat/62-grounded-policy`.

Reproduction commands from that worktree:

```text
python -m pytest tests/test_agents/test_forensic_baseline.py tests/test_agents/test_grounded_classifier.py tests/test_services/test_versioned_policy_retrieval.py tests/test_classifier_benchmark.py
python -m eval.benchmark_classifier
python -m eval.reasoning_baseline
python -m ruff check src/ tests/ eval/benchmark_classifier.py
bash scripts/check.sh
```

## Observed local results

- Focused baseline, grounded classifier, runtime retrieval, benchmark and reused corpus tests: **31 passed, 60 subtests passed**, 1.19 seconds.
- Broader runtime/API/provider-SDK contract selection: **45 passed, 18 skipped**, 60 subtests passed, 111.32 seconds. The skips require a populated PostgreSQL environment; they are not successful live-database checks.
- `python -m eval.reasoning_baseline`: category accuracy, schema validity, evidence grounding and required evidence recall each **1.0**, on the existing ten synthetic development cases.
- `python -m eval.benchmark_classifier`: baseline and candidate each **10/10**, all four class F1 values **1.0**, schema validity **1.0**, grounding errors **0**, automated sanctions **0**. Scores remain uncalibrated. Full per-case JSON and diagnostic calibration bins appear in [benchmark artifacts](../../eval/results/issue62_benchmark.json).
- `python -m eval.evaluation_corpus validate`: **53 cases**, split held-out/train/tuning **37/8/8**, SME review **53 pending**.
- Ruff check passes. Repository formatting check passes (157 files at the gate checkpoint).
- `bash scripts/check.sh` stops at Mypy: **161 errors in 19 files**. Representative existing failures: `src/services/routing_service.py:39` (`Item "None" ... has no attribute "get"`) and `src/services/feature_engineering.py:167` (nullable timestamp sorting). Existing tool-catalog/executor typing failures are on unchanged lines; no gate bypass or full green claim is made.
- Scoped Mypy on the forensic models, policy source model, retrieval service, classifier and benchmark with `--follow-imports=silent`: **success, five source files**.
- Full `pytest tests/ -q` was attempted separately but produced no completed summary before interruption. That run is **inconclusive**, not passed. The focused and broader contract selections above are the completed pytest evidence.

The code revision, normalized source hashes and paired case IDs are in the JSON metadata. A metric report is evidence only for the cases it actually executes; an unsupported or unreviewed record cannot become measured acceptance by omission.

## Held-out evidence boundary

The copied ten-case fixture is explicitly `issue62-development-v1`, with provenance linking the previously exposed baseline development set. It is **not** relabeled an independent held-out split. The harness supports strict `forensic_input` execution adapters and evaluates baseline/candidate on the same inputs. The current #64 corpus supplies 37 held-out references without a verified adapter to those facts; all are listed individually as `not_run` with their case IDs and source references. No observations are derived from suite names or expected labels. Held-out quality and full DoD acceptance therefore remain pending; the PR uses `Refs #62` and `Refs #64`.

## PR #126 CI fixture correction

The first hosted Unit Tests run at `6b43d2f` reports **one failed, 942 passed, 48 skipped, 67 subtests**, in 132.22 seconds. The failing `test_default_driver_graph_runs_scripted_tool_node` is reproduced locally before the correction: its deterministic policy fixture predates the snapshot-version retrieval contract and lacks both the trusted snapshot seam and returned `policy_version_id`.

The corrected fixture supplies a versioned snapshot and matching policy chunk through external source seams while preserving real driver ownership checks, graph execution, ToolNode dispatch and output-schema validation. It asserts published/version-scoped SQL parameters and the exact returned policy version. The corrected graph test plus retrieval, classifier and benchmark regressions pass: **23 tests**, 0.97 seconds. Production authorization and retrieval behavior are unchanged. Final-head hosted CI is verified separately after publication.

## Acceptance limits

No isolated database, hosted API/browser, external model-provider, fraud-operations SME or three-reviewer UAT result is claimed by local fixture execution. Version-scoped SQL is verified through contract tests separately from live database execution. The reused #64 corpus retains pending SME status. Release acceptance and closure remain separate from implementation completion.
