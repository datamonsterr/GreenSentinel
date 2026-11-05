# Leak Audit and Baseline Comparison (R3C vs E4)

Evaluation artifact for **Experiment R3C**: Leak audit and clean GBM baseline on `releases_v2.1`.

## 1. Executive Summary

- **Audit Rule**: Depth-3 Decision Tree fit on `train` split (28k drivers), evaluated on `validation`.
- **Acceptance Threshold**: No kept feature with univariate validation macro-F1 > 0.30.
- **Presence-Only Model**: Depth-3 Tree macro-F1 = `0.6745`, HistGBM = `0.8317`.
- **Outcome**: All kept R3C features strictly respect the `<= 0.30` limit and exclude all synthetic shortcuts.

## 2. Top 30 Features by Univariate Macro-F1 (R3C Candidates)

| Rank | Feature | Macro-F1 | OvR AUC | Status | Action |
| :--- | :--- | :---: | :---: | :---: | :--- |
| 1 | `final_distance_to_dropoff_m` | 0.4624 | 0.8382 | **FAIL (>0.30)** | Excluded (shortcut leak) |
| 2 | `initial_pickup_distance_m` | 0.4560 | 0.7825 | **FAIL (>0.30)** | Excluded (shortcut leak) |
| 3 | `min_distance_to_dropoff_m` | 0.4435 | 0.8416 | **FAIL (>0.30)** | Excluded (shortcut leak) |
| 4 | `speed_mean_kmh` | 0.3840 | 0.7667 | **FAIL (>0.30)** | Excluded (shortcut leak) |
| 5 | `stationary_ratio` | 0.3633 | 0.7347 | **FAIL (>0.30)** | Excluded (shortcut leak) |
| 6 | `stationary_duration_max_s` | 0.3611 | 0.7429 | **FAIL (>0.30)** | Excluded (shortcut leak) |
| 7 | `actual_path_length_m` | 0.3023 | 0.7437 | **FAIL (>0.30)** | Excluded (shortcut leak) |
| 8 | `pickup_dist_trend_second_half` | 0.2974 | 0.7031 | PASS | Kept in baseline |
| 9 | `stationary_duration_total_s` | 0.2970 | 0.7272 | PASS | Kept in baseline |
| 10 | `detour_ratio` | 0.2970 | 0.7795 | PASS | Kept in baseline |
| 11 | `min_pickup_distance_m` | 0.2791 | 0.7613 | PASS | Kept in baseline |
| 12 | `data_gap_max_s` | 0.2712 | 0.6928 | PASS | Kept in baseline |
| 13 | `heading_change_mean_deg` | 0.2654 | 0.7048 | PASS | Kept in baseline |
| 14 | `speed_median_kmh` | 0.2650 | 0.6897 | PASS | Kept in baseline |
| 15 | `speed_p95_kmh` | 0.2626 | 0.6384 | PASS | Kept in baseline |
| 16 | `pickup_dist_trend_first_half` | 0.2582 | 0.6995 | PASS | Kept in baseline |
| 17 | `final_pickup_distance_m` | 0.2542 | 0.7141 | PASS | Kept in baseline |
| 18 | `trip_duration_s` | 0.2492 | 0.6645 | PASS | Kept in baseline |
| 19 | `speed_disagreement_max_kmh` | 0.2482 | 0.6369 | PASS | Kept in baseline |
| 20 | `wrong_direction_ratio` | 0.2467 | 0.7301 | PASS | Kept in baseline |
| 21 | `speed_disagreement_mean_kmh` | 0.2461 | 0.6347 | PASS | Kept in baseline |
| 22 | `mock_location_ratio` | 0.2273 | 0.5589 | PASS | Kept in baseline |
| 23 | `data_gap_mean_s` | 0.2223 | 0.6096 | PASS | Kept in baseline |
| 24 | `mock_location_count` | 0.2219 | 0.5580 | PASS | Kept in baseline |
| 25 | `has_mock_location` | 0.2219 | 0.5580 | PASS | Kept in baseline |
| 26 | `speed_max_kmh` | 0.2212 | 0.6216 | PASS | Kept in baseline |
| 27 | `reached_dropoff` | 0.2151 | 0.8088 | PASS | Kept in baseline |
| 28 | `stop_count_gt_60s` | 0.2150 | 0.6651 | PASS | Kept in baseline |
| 29 | `reached_pickup` | 0.2127 | 0.6310 | PASS | Kept in baseline |
| 30 | `stop_count_gt_180s` | 0.2106 | 0.5701 | PASS | Kept in baseline |

## 3. Comparison: E4 Feature Set Audit (Same Methodology)

E4 used several features with severe leakage (>0.30 univariate F1) or direct dependency on synthetic artifacts:

| Rank | E4 Feature | Macro-F1 | OvR AUC | Leakage Mechanism |
| :--- | :--- | :---: | :---: | :--- |
| 1 | `stationary_duration_s` | 0.3708 | 0.7221 | **Shortcut leak** (captures ERR-02 stationary cutoff) |
| 2 | `approach_ssd` | 0.3688 | 0.7167 | **Shortcut leak** (>0.30 macro-F1) |
| 3 | `detour_actual_path_length_m` | 0.3023 | 0.7437 | **Shortcut leak** (captures ghost trip termination) |
| 4 | `detour_ratio` | 0.2970 | 0.7812 | Passes threshold |
| 5 | `detour_ratio_in_trip` | 0.2970 | 0.7812 | Passes threshold |
| 6 | `windows_total_stationary_s` | 0.2950 | 0.7439 | Passes threshold |
| 7 | `windows_mean_median_speed` | 0.2931 | 0.7476 | Passes threshold |
| 8 | `max_data_gap_s` | 0.2712 | 0.6927 | Passes threshold |
| 9 | `speed_p50_kmh` | 0.2682 | 0.6954 | Passes threshold |
| 10 | `guardrail_nominal` | 0.2651 | 0.6084 | **Synthetic artifact leak** (telemetry anomaly shortcut) |
| 11 | `guardrail_blocked` | 0.2651 | 0.6084 | **Synthetic artifact leak** (telemetry anomaly shortcut) |
| 12 | `windows_max_median_speed` | 0.2611 | 0.6757 | Passes threshold |
| 13 | `mean_disagreement_kmh` | 0.2565 | 0.6355 | Passes threshold |
| 14 | `speed_p95_kmh` | 0.2502 | 0.6432 | Passes threshold |
| 15 | `risk_band_approach_ssd` | 0.2492 | 0.6293 | Passes threshold |
| 16 | `has_stop_maneuver` | 0.2441 | 0.6276 | Passes threshold |
| 17 | `teleport_jump_max_kmh` | 0.2392 | 0.6062 | Passes threshold |
| 18 | `windows_total_moving_s` | 0.2332 | 0.6766 | Passes threshold |
| 19 | `maneuvers_count` | 0.2283 | 0.7173 | Passes threshold |
| 20 | `mock_ratio` | 0.2273 | 0.5589 | Passes threshold |

## 4. Presence-Only Model Audit

A classifier trained solely on binary null/non-null indicators of all 108 top-level and second-level fields achieves:
- **DecisionTreeClassifier (depth=3)**: Macro-F1 = `0.6745`
- **HistGradientBoostingClassifier**: Macro-F1 = `0.8317`

Top individual presence indicators that separate classes:

| Field | Macro-F1 | Contamination Risk |
| :--- | :---: | :--- |
| `pres_simulation_audit_err03_subtype` | 0.2645 | Correlates with cancellation / incident / audit metadata |
| `pres_platform_incident_kind` | 0.2336 | Correlates with cancellation / incident / audit metadata |
| `pres_platform_incident_occurred_at` | 0.2336 | Correlates with cancellation / incident / audit metadata |
| `pres_platform_incident_resolved_at` | 0.2336 | Correlates with cancellation / incident / audit metadata |
| `pres_platform_incident_severity` | 0.2336 | Correlates with cancellation / incident / audit metadata |
| `pres_top_platform_incident` | 0.2336 | Correlates with cancellation / incident / audit metadata |
| `pres_assignment_cancellation_actor` | 0.2120 | Correlates with cancellation / incident / audit metadata |
| `pres_assignment_cancellation_reason` | 0.2120 | Correlates with cancellation / incident / audit metadata |
| `pres_trip_cancelled_at` | 0.2120 | Correlates with cancellation / incident / audit metadata |
| `pres_trip_completed_at` | 0.2120 | Correlates with cancellation / incident / audit metadata |
| `pres_simulation_audit_severity` | 0.2111 | Correlates with cancellation / incident / audit metadata |
| `pres_assignment_arrived_at` | 0.2084 | Correlates with cancellation / incident / audit metadata |
| `pres_assignment_started_at` | 0.2084 | Correlates with cancellation / incident / audit metadata |
| `pres_driver_objection_status` | 0.1779 | Correlates with cancellation / incident / audit metadata |
| `pres_driver_objection_text` | 0.1779 | Correlates with cancellation / incident / audit metadata |

## 5. Kept Clean Features in R3C

Total clean features retained: **37**

```python
FEATURE_NAMES = [
    "speed_std_kmh",
    "speed_p95_kmh",
    "speed_max_kmh",
    "speed_disagreement_mean_kmh",
    "speed_disagreement_max_kmh",
    "speed_disagreement_ratio_gt_20kmh",
    "heading_change_total_deg",
    "heading_change_mean_deg",
    "heading_change_max_deg",
    "stop_count_gt_60s",
    "stop_count_gt_180s",
    "data_gap_max_s",
    "data_gap_mean_s",
    "data_gap_count_gt_30s",
    "teleport_jump_count",
    "teleport_jump_max_kmh",
    "mock_location_count",
    "mock_location_ratio",
    "has_mock_location",
    "planned_route_length_m",
    "detour_ratio",
    "detour_excess_m",
    "min_pickup_distance_m",
    "reached_pickup",
    "pickup_dist_trend_first_half",
    "wrong_direction_ratio",
    "reached_dropoff",
    "point_count",
    "trip_duration_s",
    "driver_rating",
    "driver_total_trips",
    "driver_acceptance_rate",
    "driver_cancellation_rate",
    "driver_w7_cancellation_rate",
    "driver_w30_cancellation_rate",
    "driver_dispute_history_count",
    "driver_prior_sanctions_count",
]
```
