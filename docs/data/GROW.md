# Grow runbook: generate more benchmark data without duplication

## Agent commands (preferred over raw CLI)

Canonical: `.agents/commands/benchmark-grow.md` (one file; all entries below
are thin pointers to it).

- OpenCode: `/benchmark-grow v2:20261012:10000` (`.opencode/commands/benchmark-grow.md`)
- Codex: `$benchmark-grow` with `PLAN=v2:20261012:10000`
  (skill `.agents/skills/benchmark-grow/` + `agents/openai.yaml`)
- Claude Code: `/benchmark-grow v2:20261012:10000` (`.claude/commands/benchmark-grow.md`)
- agy: `/benchmark-grow PLAN=v2:20261012:10000` (`.agy/commands/benchmark-grow.toml`;
  fallback: `benchmark-grow` skill via skill expansion)

All four load the same skill, environment setup, companion skills
(`benchmark-ai-agent`, `repo-testing`, `verification-before-completion`),
subagent delegation, and definition of done. Raw CLI below is what the
commands execute after setup.

One command builds additional distinct batches in parallel, dedupes them
against all prior batches, merges, and validates:

```bash
# 10k more (one batch, 4 workers for future multi-batch plans)
python scripts/benchmark/grow.py --plan "v2:20261012:10000" --workers 4

# 20k + 10k in parallel, with merged pipeline benchmark
python scripts/benchmark/grow.py --plan "v3:20261101:20000,v4:20261201:10000" \
  --workers 2 --benchmark
```

## Plan spec

`--plan "name:seed:n[,name:seed:n...]"`. Rules:

- `name` becomes the output dir (`data/benchmark-10k/<name>/`) and the
  `trip_ref` namespace (`bm_<name>_00001`…). Never reuse a name.
- `seed` must be fresh — never reuse a seed from `combined.json` or any
  `manifest.json`. Reused seeds produce identical trips and the merge aborts.
- `n` scales the v1 class mix by largest remainder (exact at 10000).

## What grow validates (exit 1 on any failure)

1. Per-batch builder gates (same 5 gates as v1).
2. Dedup vs every prior batch dir under `--base` plus `--against` extras:
   `trip_ref`, `trip_id`, `assignment_id`, and trajectory geometry hash
   (5-decimal coords). Any collision aborts the merge.
3. Merge outputs: `combined.json` (per-batch sha + counts, plan order),
   `combined_labels.csv` (`trip_ref,label,batch`).
4. `--benchmark`: offline `run_10k.py` over the merged trips; prints acc line.

## Determinism

Same plan + code → byte-identical batch `trips_sha256`. Verify with a rerun
into a scratch `--base` and compare manifest hashes.

## After growing

- Import new batch predictions: rerun the `--benchmark` flow or
  `scripts/import_benchmark.py`, then insert `benchmark_runs` /
  `benchmark_predictions` rows into `greensentinel-benchmark-db` (Railway private
  network: use `railway tcp-proxy create/delete`, never commit creds).
- Bulk `trips.jsonl` stays git-ignored; commit only the new batch
  `manifest.json` (+ sample if reviewed).
- Record the batch in `docs/data/README.md` and `DATASET_CARDS.md`.
