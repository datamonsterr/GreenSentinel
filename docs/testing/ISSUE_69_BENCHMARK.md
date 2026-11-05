# S2-F12 / Issue #69 — Phase 1 analyst benchmark

## Scope and provenance

This delivery reuses the Phase 1 analyst workflow and existing benchmark/event contracts. PR #40 (`586caec05ddb7626a1f47066b55154e74d245cc0`) was inspected as implementation history, not permission for automatic dismissal or deferred driver/A2A expansion. The implementation starts from `dede4b0` on main, including merged tracing PR #112. No tracing instrumentation, schema migration, or punitive action is introduced.

On 2026-10-03 the user explicitly authorized proceeding despite open prerequisites #64 and #68, then confirmed that reviewer observations and a staging environment are unavailable and requested completion of the runner and PR. This instruction overrides the implementation gate for this work only; it does not accept prerequisite DoD or establish release acceptance. Use `Refs #69`.

## Baseline inventory

- `eval/bench.py`: existing RAG/tool evaluation; its historical results do not establish Phase 1 reviewer concordance or MTTR.
- `eval/reasoning_baseline.py`: development smoke classification with an explicitly non-held-out fixture corpus.
- `eval/agent_conversation_benchmark.py`: existing analyst HTTP/SSE conversation runner and tool/event scoring. Its API response latency is not analyst MTTR.
- `src/services/agent_tracing.py` and `src/services/observability.py`: reuse S2-F11 observability; no new instrumentation belongs in this change.
- `src/rag/store.py`: policy retrieval used by the analyst copilot, including local markdown fallback.

## Acceptance protocol

Current [PRD section 9.3](../ba/PRD.md) requires exactly 30 fixed gold cases: 10 blatant DIC, 10 traffic false alarms, 10 technical outages. Three independent reviewers each adjudicate all 30 in randomized order. Gold decisions must be fixed before the run and hidden from runtime inputs and reviewers.

Mean MTTR starts at complete dossier render and ends at successful adjudication submission; the cohort mean must be strictly below 45 seconds. Each reviewer must match at least 28/30 fixed gold decisions; 27/30 is exactly 90% and fails the strict >90% threshold. Every guardrail and authorized-human-sanction check must pass.

The issue's historical quality/protocol wording must not be interpreted as a pooled >90% score or an inclusive >=90% threshold. PR #98 reconciles current PRD wording into explicit per-reviewer thresholds and the 28/30 boundary. This delivery follows the reconciled specification; fixture success cannot substitute for human acceptance.

## Evidence boundaries

| Environment | Evidence status |
|---|---|
| Local unit/contract fixtures | Tests validate the runner and failure boundaries; fabricated test records are test data only. |
| Local policy microbenchmark | Measures policy-search CPU work on repository documents, not human decision time or live model quality. |
| Isolated database | Not run; no configured isolated database supplied for this task. |
| Hosted/staging | Not run; no staging target supplied. |
| Independent human reviewers | Not run; no 90-decision observation set supplied. |
| Live model cost and grounding | Not measured; no live model benchmark is claimed. |

No fabricated traffic, GPS, policy, production observations, reviewer decisions or cost estimates are evidence for acceptance. Driver/A2A benchmarks remain deferred.

## DoD mapping

| Issue #69 item | Delivery / remaining evidence |
|---|---|
| Baseline completion, grounding, workflow, tools, latency, cost and version metadata | Runner contract and tests; live baseline observations remain unverified. |
| 30-case / 3-reviewer MTTR and concordance | Protocol validation and strict threshold tests; independent reviewer run remains required. |
| 100% guardrail and human-sanction integrity | Fail-closed scoring contracts; observed operational integrity remains unverified. |
| Same held-out candidate comparison, uncertainty, regressions | Paired comparison contracts and local policy microbenchmark; human/model candidate acceptance remains required. |
| PR, reproducibility, attribution and environment distinction | This report, linked artifacts, worklog, journal and PR using `Refs #69`. |

## Required completion work

- #64: supply accepted versioned corpus with fixed gold decisions and provenance.
- #68: accept correlated tracing/dashboard DoD and provide relevant staging evidence.
- #69: execute baseline and candidate against the same corpus with three independent reviewers and real observation/cost/grounding records; attach 90 decisions per run, uncertainty and every regression.
- #69: verify hosted workflow and safety without replacing observations with API latency or classifier confidence.

## Runner input contract and commands

The runner imports externally recorded and independently rated observations. It does not collect operator timing or certify the supplied statements against a live database. `status=pass` means the supplied human-observation records satisfy the implemented protocol checks; operator identity independence and the supporting artifacts still require review. Fixture, database-only and hosted API-only modes cannot satisfy human acceptance.

Manifest JSON:

- `dataset_version`, `split="held_out"`, timezone-aware `gold_fixed_at` fixed before observation begins.
- Exactly 30 `cases` with unique `case_id`, ten each of `cohort="dic"`, `"traffic_false_alarm"`, `"technical_outage"`.
- Each case has `gold_decision`, `provenance`, nonempty `source_refs` and a separate `inputs` object. Evaluation labels are not runtime inputs. `--export-inputs` exports only the explicit inputs and case IDs.
- Normalize decisions into `hold`, `dismiss`, `request_evidence`, `escalate`, `warning`, `fine`, `suspension`, `sanction`. Unknown actions are rejected. Adverse decision vocabulary is `warning`, `fine`, `suspension`, `sanction`; any warning is an adverse action. Manifest decisions and recorded sanction flags must follow this contract.

Observation JSON:

- Required `model`, `prompt_version`, evaluated `commit`, `dataset_version`, `run_id`, `environment`, `mode`, timezone-aware `started_at` and `ended_at`. `manifest_sha256` must equal SHA-256 of the exact manifest bytes.
- `mode`: `local_fixture`, `isolated_database`, `hosted`, or `human_observation`. Only the last can satisfy the human-evidence gate.
- Exactly three `reviewers`, each with an independent `id`, integer `seed` and `case_order` generated by `reviewer_order(cases, seed)`. Each reviewer gets a distinct seeded randomized sequence. Rows retain each reviewer's actual order.
- Exactly 90 unique `observations`, each with `reviewer`, `case_id`, actual `decision`, `artifact_ref`, written `rationale` and explicit `authorized_human` / `sanction_applied` booleans.
- Independently reviewed `task_completed`, `evidence_grounded`, `workflow_correct` booleans; `evidence_refs` link to manifest sources. These are imported ratings, not automatic fact verification. Gold labels never stand in for observed decisions.
- `dossier_rendered_at` and `submitted_at` measure the PRD timing boundary. Optional `mttr_seconds` must agree with these timestamps. API `agent_latency_seconds` is reported separately.
- Non-negative integer `tool_failures`; finite non-negative `cost_usd` and `agent_latency_seconds`. Unknown cost/latency may be `null`; report sample counts, withhold incomplete totals and fail the measurement-completeness gate.

Run from the repository root in a Python 3.11 environment with project dependencies:

```bash
python -m eval.phase1_benchmark --manifest /path/to/accepted-heldout.json --export-inputs --output /path/to/runtime-inputs.json
python -m eval.phase1_benchmark --manifest /path/to/accepted-heldout.json --observations /path/to/baseline-observations.json --candidate /path/to/candidate-observations.json --output /path/to/comparison.json
python -m eval.profile_policy_fallback --baseline-ref dede4b0 --repeats 60 --output docs/testing/artifacts/issue69/policy_profile.json
APP_ENV=test python -m pytest tests/test_phase1_benchmark.py tests/test_policy_fallback_optimization.py tests/test_agent_conversation_benchmark.py tests/test_services/test_agent_tracing.py tests/test_rag.py -q
bash scripts/check.sh
```

Scoring exits nonzero if baseline or candidate fails or remains unverified. Candidate pairs must have identical manifest hash and reviewer/case IDs. The report includes case-level quality, safety, time, tool and cost regressions. Concordance gets descriptive Wilson intervals; paired MTTR uncertainty uses 2,000 seeded case-cluster resamples conditional on the three reviewers. Repeated exposure/order effects and reviewer-population uncertainty are explicitly unmeasured. Acceptance remains a strict point-threshold protocol, not a confidence-bound pass shortcut.

## Measured bottleneck and optimization

The local fallback policy search constructs the same word-boundary regex repeatedly for every paragraph. The change precompiles each query token once per request. This preserves source-backed excerpts, ranking, filtering, scores and metadata, and introduces no persistent cache that could serve stale policy.

The [paired artifact](artifacts/issue69/policy_profile.json) compares the exact original method extracted from immutable baseline `dede4b0` against the candidate. It records every manifest/document hash, candidate method hash, query IDs, platform/Python version, raw samples and cProfile hotspots. There are 60 pairs with warm-up and alternating order. All complete result dictionaries match on the same four repository-document queries.

Observed mean for four queries: baseline **93.4748 ms**, candidate **91.8007 ms**, **1.79%** lower. Candidate-minus-baseline paired bootstrap 95% interval: **[-3.1618, -0.1146] ms**. This modest result measures local CPU/file work only. It does not show a 1.79% improvement in end-to-end analyst MTTR or hosted model behavior.

## Validation results

- Existing benchmark/tracing/RAG suites: **25 passed in 29.78 s**. Final new benchmark and policy regression contracts: **38 passed in 6.12 s**. A combined intermediate run passed 59 tests before four additional hardening tests were added.
- `bash scripts/check.sh`: repository Ruff and formatting pass; Mypy stops the script with **162 errors in 17 files**. Therefore the script does not reach its pytest step. Full tests are invoked separately; this check is not reported green.
- Frontend, Playwright, browser and hosted tests are not run for this backend evaluation/local policy change; no hosted acceptance is claimed.

- Immutable main baseline typecheck reproduces **162 errors in the same 17 files**: [baseline output](artifacts/issue69/mypy_baseline.txt). Scoped evaluation scripts pass Mypy with `--follow-imports=silent`.
- Full backend run was interrupted after **389 seconds**. It had emitted failures and reached 8% without a final failure summary; [partial output](artifacts/issue69/pytest_full.txt). This is not a passing full-suite result. First-failure triage is recorded separately.

- First broad-suite failure: `tests/e2e/test_driver_api_e2e.py:21`, case total `0 > 0` fails with missing local case fixtures: [triage output](artifacts/issue69/pytest_first_failure.txt). Existing CI uses `python scripts/generate_synthetic_data.py` before tests; generated synthetic test fixtures remain separate from benchmark/production evidence.

- With the existing synthetic fixture generator, broad first-failure triage yields **1 passed, 1 failed in 189.13 s**. The driver lifecycle passes; `tests/e2e/test_real_agent_driver_gemini.py:20` fails because `OPENROUTER_API_KEY` is not configured. [Seeded triage output](artifacts/issue69/pytest_seeded_first_failure.txt). No credential or fabricated provider response was supplied to make this test pass.
- Evaluated implementation revision: `c20b53b8847ba508f150d268fc2335e5f71f5bc2`. The paired artifact stores its candidate method SHA-256 and immutable pre-change commit; the later CI portability fix preserves the optimized runtime method and freezes the same original baseline.


## PR #114 CI portability correction

The initial hosted [Unit Tests run](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/actions/runs/37087027016/job/111099432136) reports **7 failed, 713 passed, 47 skipped, 14 subtests passed**. All failures are the new policy comparisons trying to read `dede4b0` through Git; `actions/checkout` uses shallow history and that commit object is absent.

The default policy baseline is now [a frozen original method](../../eval/baselines/policy_fallback_dede4b0.py), with immutable source commit, original method hash, AST integrity hash and the original stopword set. Tests and the default profiler require no historical commit object or network fetch. Custom baseline refs still use Git and fail explicitly when unavailable. No test is skipped, and CI checkout configuration is not expanded.

Local proof: **40 benchmark/policy tests passed**, then **11 policy tests passed** including a new AST integrity contract (41 total distinct focused contracts). Regression tests prohibit Git access for the default baseline and verify that unknown custom baselines do not silently fall back. Scoped Mypy uses `--follow-imports=silent --explicit-package-bases` for the namespace package.

The original measured policy artifact remains valid: the optimization is unchanged and the frozen baseline AST matches the actual pre-change method. Hosted CI after this correction is reported separately from local proof.

The correction is rebased onto main `dda427d` (including #95 and #71). Journal/worklog conflicts are resolved by retaining provider, telemetry and benchmark records. The policy runtime diff remains the same seven-line change; the frozen baseline stays tied to original `dede4b0`.
