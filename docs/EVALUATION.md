# Evaluation & Benchmarking Strategy

## Evaluation Metrics

1. **Accuracy**: Measures whether the agent produces the correct final answer on a representative test set. Target: >80%.
2. **Latency**: End-to-end response latency per query turn. Target: <3s.
3. **Tool Selection Accuracy**: Rate of selecting the correct tool with valid arguments. Target: >90%.
4. **Test Coverage**: Unit and integration test coverage across `src/`. Target: >60%.

## Running Evaluation

```bash
pytest tests/ -v --cov=src
```

Results and observations are documented in [`eval/results/report.md`](../eval/results/report.md).

## Offline Forensic Reasoning Baseline

See [REASONING_BASELINE.md](REASONING_BASELINE.md) for the input contract, evidence rules, and benchmark procedure.
Run `python -m eval.reasoning_baseline` to evaluate ten synthetic cases and save standard forensic JSON outputs,
the JSON Schema, and measured results under `eval/results/`. These are development smoke tests, not held-out accuracy.

## Versioned evaluation corpus

[`eval/corpus/v1/corpus.json`](../eval/corpus/v1/corpus.json) is the shared `eval-v1` index for RAG, tools, classification, forensic briefs, role/error and driver/A2A flows. It includes the PRD 30-case protocol as held-out cases and keeps ERR-01 through ERR-05 taxonomy coverage in a separate suite. Every record identifies provenance, allowed uncertainty, policy references, expected guardrail/action and SME review state.

Only `execution.input` is eligible for adapter projection. Expected outputs, split metadata and review labels are evaluation-only. The validator rejects label leakage, duplicate IDs, split leakage, incomplete 10/10/10 protocol coverage and automated punitive actions.

```bash
python -m eval.generate_evaluation_corpus
python -m eval.evaluation_corpus validate
python -m eval.evaluation_corpus analyze \
  --results eval/corpus/v1/inventory_results.json \
  --json-output eval/results/issue64_error_analysis.json \
  --markdown-output eval/results/issue64_error_analysis.md
```

See the [corpus runbook](../eval/corpus/v1/README.md). Do not report `pending` SME labels or `not_run` cases as measured accuracy.
