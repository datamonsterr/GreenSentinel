# Benchmark corpus object storage (Hugging Face Hub)

The bulk benchmark corpus is large and intentionally **not** committed to Git. It
lives in a public Hugging Face dataset repo and is fetched on demand.

- Repo: `datamonsterr/p-063-synthesized-trips` (override with `P063_BENCHMARK_HF_REPO`)
- URL: https://huggingface.co/datasets/datamonsterr/p-063-synthesized-trips

## Layout — one merged release

Everything lives under `releases_v1/`:

| File | Contents |
|---|---|
| `trips.jsonl` | **40,000** trips = combined (v1 + feedback-v2 + g1g2-v3, 30k) + evidence-v4 (10k). `trips_sha256` `1a0f05b3…` |
| `labels.csv` | `trip_ref,label,release` for all 40,000 |
| `manifest.json` | release/class counts, `trips_sha256`, id namespace |
| `checksums.json` | file hashes |
| `merged_sample_100.parquet` | 100-row sample of the merged file |
| `samples/` | 100-row sample per release (`v1`, `feedback-v2`, `g1g2-v3`, `evidence-v4`) and per reference source (`porto`, `nyc`, `paysim`, `multiwoz`, `sgd`, + `mipo`/`nayfeh` where licensed) |

`trip_ref` and every identity UUID are **re-indexed** in the merged file
(`rv1_<release>_<n>`, `uuid5` ids) so the 40k rows have globally unique keys — the
source corpora reused `bm_v2_*` refs and shared a seed. Each row carries a
`release` field. Regenerate with `scripts/benchmark/merge_releases.py`.

## Fetch

```bash
python scripts/benchmark/fetch_dataset.py --profile releases_v1 --out data/benchmark-10k
```

The fetcher verifies `trips.jsonl` against `manifest.json` and fails on mismatch.
A public repo needs no token; set `HF_TOKEN` for private forks.

## Seed a database

```bash
python scripts/benchmark/seed_10k_sql.py --hub-repo datamonsterr/p-063-synthesized-trips \
  --profile releases_v1 --in data/benchmark-10k --execute
```

## Publish (maintainers)

Build the release, then upload it:

```bash
python scripts/benchmark/merge_releases.py \
  --combined <build-branch>/data/benchmark-10k/combined_trips.jsonl \
  --v4 <worktree>/data/benchmark-10k/profiles/evidence-v4/trips.jsonl \
  --out /tmp/releases_v1
python scripts/benchmark/publish_dataset.py \
  --repo datamonsterr/p-063-synthesized-trips \
  --release-dir /tmp/releases_v1 --release-name releases_v1
```

Requires a write token in `~/.cache/huggingface/token` or `HF_TOKEN`. Raw
third-party datasets (`data/raw/`) and unlicensed sources are never published.

## Profile releases

### `synthesized_vietnam_trip` (1,000 trips) — **Published**

Grounded Vietnamese road coordinates across 18 pinned corridors (Hanoi and Ho Chi Minh City).

- **Hub URL:** https://huggingface.co/datasets/datamonsterr/p-063-synthesized-trips
- **Release Directory in Repo:** `synthesized_vietnam_trip/`
- **Immutable Commit SHA:** `a914d500b1c536f1dbfb59f8ea4c961bd38b5c7e`
- **Checksum (`trips_sha256`):** `c4c80903a998420b3a5d68ced5ffb5bb06709fc9ef12817651ab8b89baa628a2`

| File | Contents |
|---|---|
| `trips.jsonl` | **1,000** trips = 700 no_violation, 135 P1 (70 ERR-02, 65 ERR-03), 135 P2 (75 ERR-01, 60 ERR-04), 30 P0 (ERR-05), 0 insufficient_evidence. `trips_sha256` `c4c80903…` |
| `labels.csv` | `trip_ref,label,release,split` for all 1,000 trips |
| `manifest.json` | exact class/severity counts, splits (800 train, 200 test), 200 distinct drivers (0 leakage) |
| `checksums.json` | file hashes |
| `sample_100.jsonl` | 100-row sample committed to Git for offline preset usage |
| `sample_100.parquet` | 100-row Parquet sample |
| `metrics_strict.json` | Strict benchmark metrics: Accuracy 93.5%, Macro-F1 0.7143 |
| `metrics_enum_blind.json` | Enum-blind benchmark metrics: Accuracy 80.0%, Macro-F1 0.4107 |

### Fetch Vietnam 1k release:

```bash
python scripts/benchmark/fetch_dataset.py \
    --profile synthesized_vietnam_trip \
    --out data/benchmark-10k \
    --revision a914d500b1c536f1dbfb59f8ea4c961bd38b5c7e
```

The fetcher verifies `trips.jsonl` against recorded `trips_sha256` (`c4c80903…`).
The original 40k release (`releases_v1`) remains immutable and fetchable at revision `914a36560727f5892a24fba3a4173cb245c963da`.

---

## Published Synthetic Research Releases (`releases_v2` and `releases_v2.1`)

The realistic `releases_v2` series is published to the public Hugging Face Hub dataset repository `datamonsterr/p-063-synthesized-trips`. (Note: References to prior local-only status without write tokens are historical; both releases are now immutable and fetchable with pinned revisions). Bulk data remains git-ignored.

### `releases_v2.1` (40,000 trips) — **CURRENT SYNTHETIC RESEARCH CORPUS (Published)**

- **Status**: **Published** to Hugging Face Hub (`datamonsterr/p-063-synthesized-trips`)
- **Generator Version**: `v2.1.0-realistic` ([PR #544](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/544), [Issue #539](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/539))
- **Seed**: `20261017`
- **Checksum (`trips_sha256`)**: `d52e52ff7dd2cc7b6d23631191d1cdbf32d9f1b636f43117ad496809ac0d3fdf`
- **Class Counts**: no_violation 28,000, ERR-02 3,200, insufficient_evidence 2,400, ERR-01 2,000, ERR-03 2,000, ERR-04 1,200, ERR-05 1,200
- **Driver Split**: 70% Train (28,000), 15% Validation (6,000), 15% Test (6,000) grouped by `driver_id` (2,000 drivers; 0 leakage)
- **Release Directory in Repo**: `releases_v2.1/`
- **Immutable Commit SHA**: `abb8cc8b2464aacdcbec0aab039ef4e066f71f8e` (latest card revision: `42e37ec8ccc74e40ca7d19c3f3c353a62013c62a`)
- **Screening Subset (`dev300`)**: 300 trips validation subset, SHA-256 `cd008ee10b22520fbd71598d1718d06cf9ba9a9f3af38ca8736a11019a9a9ed9`
- **Fetch Command (pinned revision)**:
  ```bash
  hf download datamonsterr/p-063-synthesized-trips \
    --repo-type dataset \
    --include "releases_v2.1/*" \
    --revision abb8cc8b2464aacdcbec0aab039ef4e066f71f8e \
    --local-dir data/benchmark-10k
  ```
- **Local Build Command (historical reference)**:
  ```bash
  python3 scripts/benchmark/build_v2/builder.py --out data/benchmark-10k/releases_v2.1 --n 40000 --seed 20261017
  ```

### `releases_v2` (40,000 trips) — **HISTORICAL / SUPERSEDED (Published)**

- **Status**: **Published** to Hugging Face Hub (`datamonsterr/p-063-synthesized-trips`)
- **Release Directory in Repo**: `releases_v2/`
- **Immutable Commit SHA**: `cc8023b7022fdd5392a5655135712cc748967814`
- **Generator Version**: Initial realistic generator ([PR #501](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/501), [Issue #495](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/495))
- **Seed**: `20261017`
- **Checksum (`trips_sha256`)**: `9986acd1b3cefd118f2696bd4ae3c3b3dd67e0ae210808792eae5e8fd8441d5d`
- **Driver Split**: 28k / 6k / 6k trips by driver (2,000 drivers; 0 leakage)
- **Fetch Command (pinned revision)**:
  ```bash
  hf download datamonsterr/p-063-synthesized-trips \
    --repo-type dataset \
    --include "releases_v2/*" \
    --revision cc8023b7022fdd5392a5655135712cc748967814 \
    --local-dir data/benchmark-10k
  ```
- **Notes**: Superseded by `releases_v2.1` which removed the driver-objection presence shortcut.
