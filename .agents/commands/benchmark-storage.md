# benchmark-storage — host, fetch and grow the P-063 benchmark corpora

Canonical command for the object-storage side of the fraud benchmark: where the
bulk corpora live, how to pull them, how to publish a new generation, and how a
grown batch becomes the "latest benchmark". Load `benchmark-ai-agent` and
`hf-cli` before acting.

## Invoke from any harness

- OpenCode / Claude Code / Codex / agy: `/benchmark-storage` — thin pointers to this file
  (`.opencode/skills/benchmark-storage/`, `.agents/skills/benchmark-storage/`).

## 0. Backend and credentials

- Backend: **Hugging Face Hub** (public dataset repo). Default id
  `datamonsterr/p-063-synthesized-trips`; override with `P063_BENCHMARK_HF_REPO`.
- One-time auth (never commit a token):
  ```bash
  mkdir -p ~/.cache/huggingface
  printf '%s' '<hf_write_token>' > ~/.cache/huggingface/token && chmod 600 ~/.cache/huggingface/token
  # or: hf auth login
  ```
  Create a write token at https://huggingface.co/settings/tokens. A public repo
  needs no token to *fetch*; a token is required to *publish*.
- Licensing: only our **synthetic** corpora are published. Raw third-party data
  (`data/raw/`) is never uploaded; Porto attribution stays in
  `geography_provenance` (CC BY 4.0).

## 1. Fetch (reproduce a run without rebuilding bytes)

```bash
python scripts/benchmark/fetch_dataset.py --profile releases_v1 --out data/benchmark-10k
```

The fetcher verifies `trips.jsonl` against `manifest.json`/`checksums.json` and
aborts on mismatch. Then benchmark normally:
`docs/testing/manual/BENCHMARK_EVIDENCE.md`.

## 2. Publish a new generation

```bash
python scripts/benchmark/merge_releases.py --combined <build>/data/benchmark-10k/combined_trips.jsonl \
  --v4 <worktree>/data/benchmark-10k/profiles/evidence-v4/trips.jsonl --out /tmp/releases_v1
python scripts/benchmark/publish_dataset.py \
  --repo datamonsterr/p-063-synthesized-trips \
  --release-dir /tmp/releases_v1 --release-name releases_v1
```

`merge_releases.py` builds `releases_v1/` (merged 40k with re-indexed keys);
`publish_dataset.py` uploads it plus the `README.md` card in one commit. `--dry-run` stages only. After publishing, re-run the fetch to confirm
the checksum round-trips, then update `data/benchmark-10k/STORAGE.md` hashes.

## 3. Grow → validate → publish (loop)

1. Grow a new batch: `/benchmark-grow <name:seed:n>` (see
   `.agents/commands/benchmark-grow.md`). Determinism + gates must pass.
2. Merge into `combined.json` / `combined_labels.csv` (`grow.py`).
3. Rebuild the hardened profile when the generator changed
   (`build_10k_v2.py --profile evidence-v4`), verify `trips_sha256` reproduces.
4. `publish_dataset.py` (above), then update docs:
   `docs/data/DATASET_CARDS.md`, `docs/data/README.md`,
   `data/benchmark-10k/STORAGE.md`.

## 4. How to benchmark properly

- Always benchmark against a **fixed, checksummed** corpus; record the profile
  and `trips_sha256` alongside metrics.
- Report per-class recall/precision/F1, not only accuracy; the class mix is
  enrichment, not prevalence.
- Keep confidence `uncalibrated_model_confidence`; ECE/Brier diagnose the
  constant scheme, not a learned model.
- Report strict (realistic enums) and `--enum-blind` side by side.
- Frozen detector = offline, zero LLM spend; real-model runs use
  `run_10k.py --live` (staging CI) and must record model id + wall time.

## 5. Update the latest benchmark

1. Run the relevant benchmark (frozen and/or `--live`).
2. Write metrics under `notebooks/benchmark10k/` (or the CI artifact) and refresh
   `docs/data/BENCHMARK.md` tables + `docs/data/DATASET_CARDS.md`.
3. Never overwrite a frozen profile's manifest; ship a new profile name
   (e.g. `evidence-v5`) and keep the previous one fetchable.

## 6. Definition of done

- Fetch/publish round-trip verified (hash match); no secrets in repo or logs.
- `ruff check`/`format` clean; `tests/unit/test_fetch_dataset.py` and the
  builder/benchmark suites green.
- Docs and `STORAGE.md` updated with the new profile + hashes.
