# Benchmark & dataset rules (GreenSentinel)

Applies to every change touching the fraud benchmark corpora, the generator, the
runner, or object storage. Companion command: `.agents/commands/benchmark-storage.md`.

## Storage

- Bulk corpus lives on **Hugging Face Hub** (`datamonsterr/green-sentinel-synthesized-trips`,
  override `GREENSENTINEL_BENCHMARK_HF_REPO`) as one merged release `releases_v1/` (40k trips),
  never in Git. Only docs and `STORAGE.md` are committed; bulk is fetched.
- Fetch with `scripts/benchmark/fetch_dataset.py --profile releases_v1`; it verifies
  `trips.jsonl` against the recorded hash and aborts on mismatch. Build a release
  with `scripts/benchmark/merge_releases.py`, publish with
  `scripts/benchmark/publish_dataset.py --release-dir …` (streams files).
- Tokens: write token in `~/.cache/huggingface/token` or `HF_TOKEN`; never commit
  a token, never echo it, rotate after any exposure.
- Licensing: publish only our synthetic corpora and source samples whose license
  allows redistribution (Porto CC BY 4.0, NYC public domain, PaySim/MultiWOZ MIT,
  SGD CC BY-SA 4.0). MiPo and Nayfeh have no license — EDA-only, never published.
  `data/raw/` is never published.

## Growing the dataset

- Grow via `.agents/commands/benchmark-grow.md` (`grow.py`): fresh seed, new
  batch name, gates must pass, determinism proven (rerun → identical
  `trips_sha256`), dedup proven. Never edit a frozen profile in place.
- After a generator change, ship a **new release name** (`releases_v2`, …), keep the
  previous release fetchable, and record the new `trips_sha256`.

## Benchmarking properly

- Benchmark against a **fixed, checksummed** corpus; record profile + `trips_sha256`
  next to every metric.
- Report per-class recall/precision/F1, not accuracy alone; the mix is enrichment,
  not prevalence. Keep `uncalibrated_model_confidence`; ECE/Brier diagnose the
  scheme, not a learned model.
- Report **strict and `--enum-blind`** side by side. Frozen/offline runs spend
  zero LLM budget; real-model runs use `run_10k.py --live` and must record model
  id, sample size and wall time.
- The driver-based train/validation/test split exists for evaluation hygiene
  (gate classifiers fit on train, held-out dialogue templates, future fine-tune).
  A zero-shot claim is only valid on the **test** split; the full-corpus number is
  descriptive.

## CI/CD

- `.github/workflows/benchmark-dataset.yml` fetches + verifies + smoke-benchmarks
  on manual dispatch or a PR labelled `benchmark`.
- `deploy-railway.yml:benchmark-staging` runs a **real-model** sampled benchmark
  (`run_10k.py --live`) on the staging deployment; it is `continue-on-error` and
  uploads a metrics artifact + step summary. Never gate a deploy on it.

## Updating the latest benchmark

1. Run the relevant benchmark (frozen and/or live).
2. Write metrics under `notebooks/benchmark10k/` or the CI artifact.
3. Refresh `docs/data/BENCHMARK.md` tables and
   `docs/data/DATASET_CARDS.md`; update `data/benchmark-10k/STORAGE.md` hashes.
4. Never overwrite a frozen profile's manifest.
