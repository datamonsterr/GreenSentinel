# MiPo AiSq10D: measured EDA and benchmark

## Artifact and installation

The [author repository](https://github.com/TimeIsAFriend/trajectory_MiPo/tree/70a9b0140f94a1d3e2349999c621392c18c439fc) provides trajectory arrays used by the [MiPo paper](https://doi.org/10.3390/rs14215394). MiPo is a feature extraction method. AiSq10D contains Porto-derived normal trajectories and injected detour outliers; its labels are not adjudicated driver fraud. This analysis covers **one variant**, not all twelve author variants or the complete Porto archive.

Pinned revision: `70a9b0140f94a1d3e2349999c621392c18c439fc`. Full source files were acquired in temporary storage. Only a deterministic stratified slice is installed in ignored `data/mipo/`: **500 trajectories, 24,901 points, 994,543 bytes**, seed 63. Sampling selects 450 of 1,003 normal trajectories and 50 of 112 outliers without replacement. Full variant prevalence is **112/1,115 = 10.0448%**; sample prevalence is 10%.

| Source | Bytes | SHA-256 |
|---|---:|---|
| `inners.txt` | 2,016,088 | `578ed166d40affa6c7cae819622b967fa2aecacddf7caae8a16dd388f172684d` |
| `outliers.txt` | 256,588 | `88341797b61d1db8171f6a840e9e72e284c652b8909ccbad30b0fa5a9c1d07a9` |
| Installed `sample.jsonl` | 994,543 | `1929e89f4e62c367371ff9da7ec2d7e814cd4728dfd6332ed56c9750f359557e` |

No license file appears in the pinned author repository. Upstream Porto licensing does not establish redistribution rights for author transformations. Raw samples remain ignored. The committed manifest inside [profile.json](../../notebooks/mipo/profile.json) records URLs, checksums, row counts, and selection rules; it contains no raw trajectories.

## Reproduce

```bash
python -m pip install numpy==2.4.6
python scripts/eda_mipo.py --download
# Subsequent offline rerun, using installed slice:
python scripts/eda_mipo.py
```

The downloader verifies pinned source SHA-256 before sampling. The analysis script requires only NumPy beyond the Python standard library. Notebook display additionally requires a Jupyter/IPython environment. The script was executed; notebook cells were compiled successfully, but a notebook kernel was not available in the existing environment. Dependencies are isolated from runtime application dependencies. Download size is approximately 2.27 MB; the staged slice is below 5 MB and 500 rows. The [script](../../scripts/eda_mipo.py) writes complete distribution tables and timings to [profile.json](../../notebooks/mipo/profile.json). The [notebook](../../notebooks/MIPO_EDA.ipynb) reruns the same calculations and displays [distribution plots](../../notebooks/mipo/distributions.svg) and [planar trajectories](../../notebooks/mipo/trajectories.svg).

## Actual schema and quality

Each source line is an array of numeric `[x, y]` pairs. It contains no header, trip identifier, driver identifier, timestamp, reported speed, bearing, accuracy, pickup point, trip state, dispute text, or device state. `label` comes from the filename; `source_row` is a local zero-based ordinal added during installation. Neither is an original platform trip identifier.

All 24,901 points are finite; all violate geographic longitude/latitude bounds if interpreted directly as WGS84. Observed x spans **90,786.660–97,451.372**; y spans **−13,988.079–−1,843.002**. The coordinate reference system, origin, scale, and transformation parameters are unverified. Distances below use **source XY units**, not meters. No Folium geographic basemap is rendered because it would misrepresent these coordinates. Planar plots are valid for geometry inspection only; their axes are independently scaled for layout.

The sample has zero exact duplicate trajectories. There are **97 zero-length segments among 24,401 segments (0.3975%)**. These indicate repeated locations; without timestamp intervals they do not establish stop duration. Empty, malformed, non-finite, or shorter-than-two-point trajectories fail the parser. Original files are valid JSON lines under this parser; absent platform fields have 100% unavailability.

## Distributions

All statistics describe the installed slice. Length sums Euclidean step distances. Tortuosity divides that sum by endpoint displacement. Turns are unsigned angles between successive nonzero displacement vectors, in radians. Endpoint distance is narrowly distributed because this benchmark variant selects a particular source/destination pair.

| Feature | Min | P25 | Median | P75 | P95 | Max |
|---|---:|---:|---:|---:|---:|---:|
| `points` | 37.000 | 46.000 | 49.000 | 54.000 | 60.000 | 75.000 |
| `length_xy` | 11774.197 | 12224.700 | 12315.006 | 13786.802 | 15600.634 | 17872.969 |
| `endpoint_distance_xy` | 9373.867 | 9570.191 | 9619.406 | 9665.564 | 9747.662 | 9816.632 |
| `tortuosity` | 1.237 | 1.273 | 1.278 | 1.419 | 1.621 | 1.864 |
| `step_p50_xy` | 183.134 | 265.612 | 290.257 | 315.941 | 351.294 | 396.844 |
| `step_max_xy` | 322.725 | 433.124 | 455.566 | 477.589 | 497.253 | 593.274 |
| `zero_step_fraction` | 0.000 | 0.000 | 0.000 | 0.000 | 0.021 | 0.064 |
| `turn_mean_rad` | 0.238 | 0.335 | 0.389 | 0.448 | 0.568 | 0.752 |

Full P05, mean, standard deviation, per-class quantiles, coordinate distributions, and segment distributions are in [profile.json](../../notebooks/mipo/profile.json). Outlier median length is **15,088.143** versus **12,292.653** for normal trajectories; median tortuosity is **1.5622** versus **1.2769**. Median points are **56** versus **49**. Endpoint distances remain similar (**9,592.819** versus **9,620.172**), consistent with detour injection within an origin/destination cohort. This construction makes route stretch a favorable baseline; it does not imply transfer to other anomaly types.

## Empirical detector benchmark

This is an **unsupervised transductive ranking benchmark on the same 500 trajectories**, with labels used only to evaluate ranking. There is no train/test split, classifier training, tuned threshold, held-out accuracy claim, or production fraud precision claim. Higher scores mean more anomalous. AUROC uses pairwise comparisons with half credit for ties. Average precision groups equal scores at the same threshold. No parameter search was performed.

| Baseline | AUROC | Average precision |
|---|---:|---:|
| Constant score / prevalence reference | 0.5000 | 0.1000 |
| Route tortuosity | 0.9444 | 0.6124 |
| Generic geometric LOF, k=20 | 0.7593 | 0.2356 |

LOF uses the eight features listed above, population-standardized on the same evaluation batch, Euclidean distances, exactly 20 nearest neighbors, and deterministic index order for equal distances. It is a NumPy implementation of the LOF density-ratio equations, **not a reproduction of MiPo middle-polar features or the paper's LOF implementation**. Standardization and neighbor reference use the full batch because this is transductive detection. Do not present the score as future-event generalization. No confidence interval is claimed from this single seeded slice.

Timing environment: Python 3.11.15; NumPy 2.4.6; AMD Ryzen 5 2600 Six-Core Processor; 12 logical CPUs; Linux-7.2.4-arch1-2-x86_64-with-glibc2.44. Each operation has one untimed warm-up and seven timed repetitions using `perf_counter`; all 500 rows are processed each time. Local file reads are warm-cache. Network download, import, plotting, schema conversion, database writes, model serving, and LLM adjudication are excluded. CPU affinity/thread limits were not pinned; concurrent host load may affect latency.

| Operation | Median ms / 500 trips | Min–max ms | Trips/s at median |
|---|---:|---:|---:|
| ingestion | 31.453 | 24.780–40.083 | 15,897 |
| feature_extraction | 84.096 | 80.165–96.088 | 5,946 |
| lof_fit_score | 34.427 | 32.344–34.810 | 14,523 |

The LOF implementation forms a quadratic distance matrix and is suitable for this small slice only. These results cannot establish the PRD production throughput or adjudication latency targets.

## Unsupported measurements and next benchmark

Speed, acceleration, bearing relative to north, SSD seconds, timestamp gaps, daily/weekly activity, pickup-directed DAVI, time to alert, and cancellation outcomes are **unavailable**. A synthetic 15-second clock would be an explicit simulation, not recovered telemetry. A transformed benchmark may have altered points, so source sampling cadence alone does not recover event timing.

Next: recover the documented coordinate transform or use original Porto WGS84 polylines for telemetry ingestion; retain timestamp provenance and missingness. Benchmark each MiPo variant separately. For supervised evaluation, group original trajectory families before splitting, including perturbed relatives; exact hashes alone cannot identify those relatives. For live scoring, use prefixes and avoid completed endpoints. Report per-variant AUROC/AP, repeated seeds and uncertainty, runtime scaling, and alert burden at fixed thresholds. Evaluate driver fraud only with independent platform evidence and adjudicated outcomes.

See [fraud research](MIPO_FRAUD_RESEARCH.md) and [telemetry mapping](MIPO_TELEMETRY_MAPPING.md).

## Operational import boundary

`scripts/import_mipo.py` stores the pinned sample in `app.research_trajectories`.
MiPo AiSq10 coordinates are planar with an unknown CRS, so they remain in the
`points_xy` research column and are never written to operational PostGIS
telemetry or route columns. The importer is idempotent on source, revision, and
source row and requires `DATABASE_URL` or `MIGRATION_DATABASE_URL` at runtime.

The operational map uses WGS84 pickup/dropoff coordinates and timestamped
telemetry. MiPo labels remain benchmark labels and are not fraud case outcomes.
