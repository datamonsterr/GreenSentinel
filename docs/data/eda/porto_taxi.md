# Porto Taxi UCI: measured EDA for 10k fraud-benchmark priors

Geometry/kinematics + missingness only. Porto has no intent labels; nothing here is a fraud label.
Scope: which `config/telemetry_distribution.yaml` assumptions measured Porto values replace.

## Artifact and sample rule

- File `data/raw/porto_taxi_uci/train.csv.zip`, 533,605,607 B,
  sha256 `210dd0a20da66a8fc2de3440aecd84670921bc257591f8365a4475e31453c5ea`.
  License CC BY 4.0; credit Moreira-Matias et al., UCI, doi:10.24432/C55W25.
- Full data: 1,710,670 trips, 2013-07-01–2014-06-30 UTC, 448 drivers.
- Sample: seed 63, n = 50,000, proportional allocation over
  CALL_TYPE (A/B/C) x weekday/weekend (UTC date arithmetic), per-stratum reservoir
  in file order. DAY_TYPE is constant `A` (no signal); MISSING_DATA=True is 10 trips
  (census below, 0 landed in sample). Allocation:
  Axwkd 8078, Axwke 2583, Bxwkd 17771, Bxwke 6134, Cxwkd 9857, Cxwke 5577.
- Streamed via `zipfile`, two passes, no extracted files. Script: `scripts/eda_porto.py`;
  machine values: `notebooks/porto/profile.json`. Runtime 70.7 s
  (pass1 29.2 s, pass2 34.5 s, metrics 6.7 s; Python 3.11.15, NumPy 2.4.6).
- Conventions: duration = points x 15 s (nominal cadence, no per-point timestamps);
  distances = haversine on WGS84 lon/lat; speed = segment haversine / 15 s;
  stop run = consecutive segments with displacement < 15 m
  (`segment_min_displacement_m`), duration = run length x 15 s.

## TelemetryPayload field mapping (`src/models/schemas.py`)

| Payload field | Porto source | Notes |
|---|---|---|
| `position.latitude/longitude` | POLYLINE `[lon,lat]` sequence | Direct; 2,442,973 points in sample |
| `occurred_at` start | TIMESTAMP (unix trip start) | Start only; per-point times = start + k x 15 s assumed |
| `position.accuracy_m` | absent | No accuracy column |
| `speed_mps` (reported) | absent | Derived from positions only |
| `bearing_deg` | absent | Derivable, not measured here |
| `app_state`, `network_state`, `gps_state`, `mock_location_reported`, `latency_ms` | absent | No device/platform fields |
| `distance_to_pickup_m`, `davi_score`, `data_gap_s` | absent (server-computed by design) | No pickup coords in Porto |
| Trip context | CALL_TYPE A/B/C, TAXI_ID, MISSING_DATA flag | No pickup/dropoff addresses, no fares |

## Distributions (sample n = 50k; pooled segments 2,393,152)

Trips with >= 2 points: 48,995. Empty `[]` polylines: 179 sample / 5,901 full (0.34%).

| Feature | p05 | p25 | p50 | p75 | p95 | max | mean |
|---|---:|---:|---:|---:|---:|---:|---:|
| `points` | 12 | 28 | 41 | 59 | 103 | 2096 | 48.9 |
| `duration_s` (= pts x 15) | 180 | 420 | 615 | 885 | 1545 | 31440 | 732.9 |
| `path_m` | 963 | 2401 | 3964 | 6573 | 14942 | 381991 | 5537 |
| `endpoint_m` | 515 | 1538 | 2617 | 4200 | 9006 | 368904 | 3389 |
| `tortuosity` (1,013 endpoint-0 excluded) | 1.124 | 1.278 | 1.445 | 1.750 | 3.852 | 18211 | 10.58 |
| `segment speed pooled m/s` | 0.067 | 1.006 | 5.841 | 11.174 | 23.987 | 24540 | 7.685 |
| `per-trip speed_max m/s` | 10.1 | 14.1 | 17.9 | 27.2 | 51.6 | 24540 | 25.3 |
| `per-trip max_stop_run_s` | 0 | 30 | 45 | 75 | 255 | 15255 | 86.9 |

- Trip-level mean speed (path/duration of means): 5537 / 732.9 = 7.55 m/s;
  of medians: 3964 / 615 = 6.44 m/s. Replaces Posisi-derived 9.26 m/s for taxi priors.
- Implausible segments (> 50 m/s, `implausible_speed_mps`): 0.1509% of segments;
  per-trip share p95 = 0.017, mean 0.003. Honest data is not jump-free:
  ~5% of trips contain >= 1 segment above the ERR-05 threshold.
- Zero-displacement segments: 28.9% of trips contain >= 1; per-trip fraction
  p75 = 0.015, p95 = 0.050.
- Stop runs (>= 15 m criterion): 7.95% of trips have max run >= 180 s (ERR-02 SSD line).
  In-trip dwell only, not pre-pickup stall; ERR-02 proxy, not label.
- By CALL_TYPE (n / path p50 / tortuosity p50):
  A 10,661 / 4191 m / 1.481; B 23,905 / 3781 m / 1.417; C 15,434 / 4171 m / 1.469.

## MISSING_DATA census (full data, not sample)

- Rate 10 / 1,710,670 = 5.8e-6. Trip-level flag only; unusable as a gap/dropout rate
  for `insufficient_evidence` mixing. Point counts of the 10: 1, 1, 11, 14, 27, 43, 51, 53, 285, 483.

## Drivers, time split (full-data driver counts; sample time split)

- 448 drivers; trips/driver full: p05 1309, p25 2694, p50 3732, p75 5023, p95 6303,
  max 10746, mean 3818 (~10/day). Sample covers 439/448 drivers. ERR-04 frequency baseline.
- Night starts (00-06/22-24 UTC): 24.4%. Weekend starts: 28.6%.

## Limitations

- No per-point timestamps beyond nominal 15 s cadence; durations assume exact clock.
- No pickup coords, fares, accuracy, speed/bearing reports, device or network state.
- Day/night and weekday/weekend use UTC date arithmetic; Lisbon local (WET/WEST)
  differs, misclassifying trips near UTC midnight.
- Tortuosity mean (10.58) is tail-driven (near-zero endpoints); use quantiles.
- One seeded sample; no uncertainty bands. No intent/fraud labels anywhere.

## Verdict: yaml assumptions Porto REPLACES vs keeps

REPLACE (measured, WGS84): 15 s cadence (was documented-only); mean trip speed 9.26
with 7.55 m/s mean / 6.44 m/s median; tortuosity quantiles with
1.124/1.278/1.445/1.750/3.852 (was unit-free MiPo); honest jump rate 0.15% segments
> 50 m/s; zero-step and stop-run shares above; per-driver trip-count distribution
(median 3732/yr).

KEEP as assumptions (Porto cannot measure): `missed_ping_probability` 0.05 /
outage 2% (no per-point gaps; MISSING_DATA flag rate 5.8e-6 is a different process);
accuracy log-normal; reported-speed null rate; bearing noise; app/network/gps/mock
states; start-distance-to-pickup Uniform(500, 2000).

Related: [SURVEY.md](../SURVEY.md), [MIPO_EDA.md](../MIPO_EDA.md),
[TELEMETRY_DISTRIBUTION.md](../TELEMETRY_DISTRIBUTION.md).
