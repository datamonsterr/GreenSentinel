# NYC TLC Yellow 2024-01 EDA (Issue #250)

Method: `scripts/eda_nyc_tlc.py` on `data/raw/nyc_tlc_sample/yellow_tripdata_2024-01.parquet`
(public domain, 2,964,624 rows, 19 fields, tabular zone IDs, NO GPS).
Profile: `notebooks/nyc/profile.json`. Validity rule: `0<duration_s<=10800`,
`0<trip_distance_mi<=100`, `fare_amount>0` → **2,867,608 valid (96.73%)**.
Excluded: 870 duration≤0, 1,983 duration>3h, 60,371 distance 0, 59 distance>100mi,
38,341 fare≤0 (overlapping).

## A. Duration / distance (valid slice)

| Quantity | Mean | Median | p95 | p05–p99 |
|---|---|---:|---:|---|
| `duration_s` | 897.3 (14.9 min) | 703 (11.7 min) | 2272 (37.9 min) | 214–3582 |
| `distance_mi` | 3.29 | 1.70 | 13.96 | 0.51–20.02 |
| `distance_m` | 5298 | 2736 | 22466 | 821–32219 |
| implied speed m/s | 5.43 | 4.32 | 11.72 | 2.14–16.53 |

vs assumption (Posisi 11.94 km / 21.50 min, 9.26 m/s): NYC trips shorter and
slower (Manhattan taxi, dense urban). NYC mean speed 5.4 m/s, median 4.3 m/s.

## B. Time-of-day scheduler shape (pickup, valid slice)

Weekday share Mon–Sun (dayofweek 0–6): 0.1370 / 0.1565 / **0.1676 Wed peak** /
0.1451 / 0.1381 / 0.1419 / 0.1138 Sun low. Weekend share 0.2557.
Hour share: trough 04:00 0.0053, 05:00 0.0061; ramp from 06:00; plateau
10:00–22:00 (0.047–0.072); **peak 18:00 0.0719**, 17:00 0.0698; night decay after 22:00.
Use these two vectors directly as synthetic scheduler weights (normalize; note:
NYC January, taxi-only, northern winter — shape prior, not Vietnam calibration).

## C. Fare quantiles (USD, valid slice)

`fare_amount`: mean 18.49, p50 12.80, p75 20.50, p95 60.40, p99 73.00.
`total_amount`: mean 27.34, p50 20.16, p95 79.89. Informational only (VND/fare
model differs; no YAML fare key exists).

## D. Payment mix + dropout (informational)

Payment (valid): credit `1` 80.10%, cash `2` 14.72%, no-charge `0` 4.02%,
dispute `4` 0.79%, unknown `3` 0.37%. `store_and_fwd_flag`: N 95.60%, null 4.02%,
**Y 0.38%** (10,890) — device-store dropout proxy exists but tiny and
mechanically different from network/app-crash gaps.
**Dropout/cancellation has NO signal here**: completed trips only; no
cancellation, no-show, or gap columns. ERR-01/ERR-02 and `insufficient_evidence`
rates cannot be measured from this file.

## E. Config verdict (`config/telemetry_distribution.yaml`)

- `speed.mean_trip_speed_mps: 9.26` — **CONFIRMED** (retain; NYC 5.4 mean is
  Manhattan-taxi specific, slower than SE-Asia mixed car/motorbike; not transferable).
- `speed.moving_speed_mps.car / .motorbike` (mean 9.3 each) — **CONFIRMED**
  (no per-mode data in TLC; equal-split assumption stands).
- `scenarios.normal_trip.on_trip_s` (uniform 120–300) — **CONFIRMED** (partial
  post-pickup observation window, not full-trip duration; NYC full-trip p25 436 s
  does not contradict it).
- `scenarios.technical_dropout.*` — **CONFIRMED** (no change; TLC `store_and_fwd`
  Y 0.38% is a different mechanism, reference only).
- No new YAML keys added. Scheduler weights live in `notebooks/nyc/profile.json`
  (`weekday_share`, `hour_share`); wire into generator in follow-up if wanted.

## F. Limitations

January-only (winter seasonality); NYC taxi only (no motorbike, no ride-hail);
airport/overnight-rate fare structure differs from Vietnam; validity caps
(3 h, 100 mi) chosen, not measured; `store_and_fwd` null 4% unexplained;
no trajectory/GPS, no cancellation labels, no per-driver IDs used.
