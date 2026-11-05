# Mapping Porto and MiPo trajectories to the telemetry contract

The [telemetry schema](../architecture/schemas/telemetry-event.schema.json) is an operational event contract. MiPo is a feature extraction method; its derived benchmark trajectories and the underlying [Porto Taxi archive](https://archive.ics.uci.edu/dataset/339/taxi%2B) are research data. A benchmark row is not automatically a driver event. Preserve raw files and label provenance separately from replay events. The table below applies to the **original Porto `POLYLINE`**, not automatically to MiPo benchmark variants: the inspected `AiSq10D` author files contain coordinates outside WGS84 latitude/longitude ranges and carry no per-point timestamps. Their coordinate reference system and clock provenance must be established before any conversion to this contract.

## Source-to-contract map

| Contract field | Porto source | Replay rule | Evidence status |
|---|---|---|---|
| `payload.position.latitude`, `.longitude` | `POLYLINE` pair `[longitude, latitude]` | Reverse pair order; reject invalid ranges and empty points | Observed coordinates |
| `occurred_at` | `TIMESTAMP` trip start; points nominally 15 seconds apart | `TIMESTAMP + 15 * point_index` seconds in UTC | Inferred point time; nominal cadence, not recorded per-point clock |
| `driver_id` | `TAXI_ID` | Stable namespace UUID derived from source and ID | Pseudonymous mapped identifier |
| `trip_id`, `assignment_id`, `correlation_id` | `TRIP_ID`; no assignment/correlation IDs | Stable namespace UUIDs derived from source and trip; mark assignment as replay surrogate | Synthetic join keys, not observed assignment |
| `event_id`, `sequence`, `source` | Trip and point order | Stable UUID per trip/index; zero-based point index; source identifies exact artifact/version | Replay metadata |
| `payload.position.accuracy_m` | Absent | Required key with `null` | Unknown, never zero or a guessed precision |
| `payload.app_state`, `.network_state`, `.gps_state` | Absent | `unknown` | Unknown, including GPS provider integrity |
| `payload.mock_location_reported` | Absent | `null` | No mock-provider evidence |
| `payload.speed_mps`, `.bearing_deg` | Absent | `null` in raw replay; derived kinematics stored as separately tagged features | Not sensor measurements |
| `payload.distance_to_pickup_m`, `.davi_score` | No pickup assignment or planned route | `null` unless independent booking/route evidence is supplied | Unavailable for raw archive |
| `payload.data_gap_s` | Nominal cadence only | `null`; point omission is not directly observed | Unknown |
| MiPo benchmark label | Derived anomaly dataset | Keep outside telemetry event, tied to source trip and variant | Trajectory outlier label, not adjudicated fraud |

The normalized event uses `event_type = "telemetry.observed"` and `schema_version = 1`. Do not set `gps_state = "valid"` simply because a coordinate exists. Use `unknown` until quality or provenance is established. Maintain a sidecar manifest with source URL, revision/checksum, row index, coordinate order, CRS, timestamp inference, replay UUID namespace, and benchmark label origin. Do not expose `TAXI_ID` or `TRIP_ID` in the public event envelope. Reject projected or otherwise unknown-coordinate-system benchmark variants for geodetic replay until a documented transform is available; do not clamp or relabel those values as degrees.

## Contract adjustment

The schema previously required numeric `accuracy_m`, which the Porto archive does not report. It now requires the field but accepts `null`; the Pydantic and TypeScript types match. This changes an unknown fact into explicit missingness while retaining coordinate bounds and nonnegative measured accuracies. The database column already accepts null. The API should preserve null on ingestion; any downstream default such as `5.0` must be removed before using archival replay as evidence.

## What to evaluate

Validate every replayed envelope against JSON Schema and Pydantic; report failures by cause. Compare original point counts and coordinates against the replay to catch indexing and coordinate-order errors. Report the fraction of null accuracy, unknown states, and inferred timestamps. Benchmark decoding, event construction, validation, and feature extraction separately from model fit and scoring. Evaluate anomaly labels only against the particular MiPo benchmark variant; no benchmark score establishes DIC intent, GPS spoofing, or the PRD's overturned-sanction false alarm rate.

For [PRD](../ba/PRD.md) Phase 1 `UC-L06-04`, replay can supply map breadcrumbs and route/kinematic anomaly evidence to an analyst case. Pickup-direction and stall decisions require a known pickup coordinate and actual event-time coverage. Fraud conclusions and sanctions require additional trip, cancellation, traffic, device, and human-review records. [Research and test design](MIPO_FRAUD_RESEARCH.md) describes the boundary for each `ERR-01`–`ERR-05` class.

## PRD use-case fit

| PRD use case / requirements | What the data can support | Remaining dependency |
|---|---|---|
| Phase 1 `UC-L06-04`, `FR-L06-10` | Breadcrumb and geometric anomaly panel in the analyst dossier, after a valid coordinate transform or original Porto replay | OSRM route, assignment, app errors, driver excuse, and provenance need other feeds |
| Phase 1 `FR-L06-11`–`12`, `FR-L06-17` | Anomaly evidence can be attached to a review and audit snapshot | Role control, human approval, rationale, and immutable audit are application behavior |
| Phase 2 `UC-L06-01`, `FR-L06-01`–`04` | Offline detector prototyping on completed routes | Live pre-cancellation prefixes, pickup assignment, timing, passenger prompt and no-leakage checks |
| Phase 2 `UC-L06-02`/`03`/`06`, `FR-L06-05`–`09` | Route evidence can supplement an investigation | Dispatch, payments, app/network logs, and safe driver submission are absent |
| Phase 3 `UC-L06-05`/`07`, `FR-L06-13`–`16`, `FR-L06-18` | Historical anomaly scores could be one calibration input | Appeals, overturned verdicts, policy versions, canary metrics, and rollback controls are absent |

The installed `AiSq10D` benchmark lacks both a verified coordinate transform and timestamps. It can therefore benchmark **offline route-shape ranking** immediately, but it cannot directly populate compliant `telemetry.observed` events. Original Porto rows may support replay under the explicit inference rules above after that source is separately acquired and validated.
