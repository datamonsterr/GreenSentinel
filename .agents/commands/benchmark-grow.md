# benchmark-grow — grow the P-063 fraud benchmark (canonical command)

Generate additional distinct labeled fraud-benchmark batches in parallel,
fully validated. Use when asked to generate more benchmark data (10k more,
20k, extra batches), extend dataset coverage, or validate/grow the dataset.

## Invoke from any harness

- OpenCode: `/benchmark-grow v2:20261012:10000` (`.opencode/commands/benchmark-grow.md`)
- Codex: `$benchmark-grow` with `PLAN=v2:20261012:10000` (skill pointer +
  `agents/openai.yaml`)
- Claude Code: `/benchmark-grow v2:20261012:10000` (`.claude/commands/benchmark-grow.md`)
- agy: `/benchmark-grow PLAN=v2:20261012:10000` (`.agy/commands/benchmark-grow.toml`)

All four are thin pointers to this file. Plan spec is `name:seed:n[,name:seed:n...]`.

## 0. Environment (required — raw `python3` will fail)

- Python: `.venv/bin/python` (repo venv; numpy/pydantic/pyyaml/pytest present).
  Extras via `uv pip install --python .venv/bin/python <pkg>`.
- GitHub CLI: `export GH_CONFIG_DIR=$HOME/.config/gh` first (account `datamonsterr`).
- Railway CLI: `~/.railway/bin/railway` (not on PATH). Project `caring-renewal`,
  benchmark DB `p063-benchmark-db` in `dev` env. No local `psql`; use `.venv`
  `psycopg` + `railway tcp-proxy create/delete`. Never commit creds.
- Never make live LLM calls from benchmark scripts (offline guards enforced).

## 1. Companion skills (load before acting)

- `benchmark-ai-agent` — benchmark methodology (metrics, calibration, leakage discipline).
- `repo-testing` — test placement/execution; `verification-before-completion`
  before claiming done; `quality-checks` for lint/format gates.
- `jev-skill-selector` may already have routed these; else load explicitly.

## 2. Subagent delegation (per `.agents/subagents.json` tiers)

- Dataset discovery/acquisition → `data-scout` (cheap tier).
- Per-dataset EDA → `data-analyst` (reasoning tier), one agent per dataset, parallel.
- Synthesizer/generator implementation → `implementer` (reasoning tier).
- Test triage → `test-runner`. Docs → `doc-writer`.
- If a harness rejects a type (model-not-found), retry the same prompt with
  the `general` type — task content is harness-neutral.

## 3. Grow workflow

1. Pick plan `name:seed:n` batches. `name` is new (dir + `bm_<name>_` refs);
   `seed` is fresh (never in `combined.json` or any `manifest.json`); `n`
   scales the v1 class mix (exact at 10000). Full runbook: `docs/data/GROW.md`.
2. Run: `python scripts/benchmark/grow.py --plan "<plan>" --workers 4 [--benchmark]`.
   Exit 1 on gate FAIL, ID/geometry collision, or hash mismatch — fix, never force.
3. Confirm merge outputs: `combined.json`, `combined_labels.csv` (`trip_ref,label,batch`).
4. Record the batch in `docs/data/README.md` + `docs/data/DATASET_CARDS.md`;
   bulk `trips.jsonl` stays git-ignored; new batch `manifest.json` is committed.
5. Publish the refreshed corpora to object storage: `scripts/benchmark/publish_dataset.py`
   (see `.agents/commands/benchmark-storage.md`). Rebuild the hardened profile when the
   generator changed, verify `trips_sha256` reproduces, refresh `data/benchmark-10k/STORAGE.md`.
6. Optional Railway import of new predictions (new `benchmark_runs` row):
   create proxy, import, delete proxy. Never touch production data.

## 4. Definition of done

- `test_grow.py` + builder/synth unit suites green; `ruff check`/`format` clean.
- Determinism proven (rerun → identical `trips_sha256`); dedup proven
  (reused seed aborts); gates all PASS; metrics reported with the
  uncalibrated-confidence caveat; no secrets in repo.
