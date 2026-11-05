# Ride-hailing fraud and GPS research (S1-DA-04)

**Research date:** 2026-09-27. **Scope:** what public Grab and Uber engineering material tells GreenSentinel about telemetry quality and fraud signals, and which signals the current feature pipeline already computes. Only statements found in the cited pages are reported; anything else is marked **needs verification**.

Related: [telemetry distribution proposal](TELEMETRY_DISTRIBUTION.md), [MiPo fraud research](MIPO_FRAUD_RESEARCH.md), [MiPo EDA](MIPO_EDA.md). Feature names refer to `FeatureWindow` in `src/services/feature_engineering.py`, introduced by PR #43 (`son/da02-features`, not yet merged at the time of writing).

## 1. Sources

### Grab

| Source | What it says | What GreenSentinel takes from it |
|---|---|---|
| [Grab-Posisi blog](https://engineering.grab.com/grab-posisi) and [paper PDF](https://engineering.grab.com/files/Grab-Posisi_An_Extensive_Real-Life_GPS_Trajectory_Dataset_in_Southeast_Asia.pdf) (Huang et al., PredictGIS'19) | Singapore and Jakarta, 2019-04-08 to 2019-04-21. Six categories of 14,000 trajectories each (SIN car iOS/Android, JKT car iOS/Android, JKT motorcycle iOS/Android). 84K trajectories, **88,847,080 pings** (paper; the blog says "more than 80 million"), 1,003,510 km, 30,104 h. **1 s sampling; "> 90%" of consecutive-ping intervals are 1 s**; breaks occur, for example in tunnels. Average length 11.94 km (abstract; §3.2 says 11.90 km) and duration 21.50 min. Each ping has latitude, longitude, UTC timestamp, accuracy (m), bearing (degrees from true north), speed (m/s). | The only public Southeast-Asian dataset with the fields our `TelemetryPayload` needs, including a motorcycle label. It is the calibration target for every assumed parameter in the distribution proposal. Access requires email to Grab; **commercial use is prohibited**. |
| Same paper, §3.4 accuracy | Android accuracy is a 68% radius; **0.0 means unavailable**. Android bearing is (0, 360] and **0.0 means invalid**; Android speed **0.0 means invalid**. iOS reports bearing 180 when two consecutive pings share a location. Android accuracy maxes at **127 m**; iOS reaches **149 km** with a long tail. Ping counts peak around **10 m** accuracy and change trend near **50 m**. The authors warn to be cautious when using accuracy. | Our schema accepts `0` as a valid accuracy, speed, and bearing. A Posisi importer must map Android `0.0` to `null`. Accuracy semantics differ by OS, so a device-platform field is needed before accuracy thresholds become trustworthy. |
| [Graph networks](https://engineering.grab.com/graph-networks) | Nodes are accounts, devices, and IP addresses; edges are shared devices, IPs, and transaction flows. Targets are device farming ("hundreds of other fake accounts" for promo and payment fraud) and money laundering. Uses a graph database, network features such as "number of hops between two users", and GNNs. Mentions "device farms and GPS spoofing apps". | Coordinated fraud needs entity relationships that single-trip telemetry cannot show. Out of scope this sprint (section 4). |
| [Trust Counter Service](https://engineering.grab.com/using-grabs-trust-counter-service-to-detect-fraud-successfully) | Self-service counters over time windows; pre-aggregated tables at **15-minute, hourly, and daily** granularity. Example: one person acting as both driver and passenger to farm cashless-payment promotions, detected by counting driver–passenger pair interactions against thresholds. p99 read < 150 ms; peak about 5k QPS. | A driver–passenger pair counter is a cheap collusion signal (ERR-03/ERR-04) once trips carry passenger IDs across a history window. |

### Uber

| Source | What it says | What GreenSentinel takes from it |
|---|---|---|
| [Mastermind](https://www.uber.com/us/en/blog/mastermind/) | Rules engine for payment fraud, account takeover, driver–rider collusion, and promotion abuse. Graduated actions: moderate risk slows ride requests; high risk may reject and ban. 300 complex rules run in about 30 ms. Analysts write rules in a Python-AST DSL. The article does not mention GPS spoofing. | Supports versioned deterministic rules for triage. GreenSentinel differs by design: the output is a ranked case for a human, never an automatic ban. |
| [Project RADAR](https://www.uber.com/us/en/blog/project-radar-intelligent-early-fraud-detection/) | Anomaly detection on payment time series (unpaid orders, chargebacks) with the Orbit KTR Bayesian model; FP-Growth mines rule candidates that require high precision; analysts review via Jira before rules go live. | Human-in-the-loop review before enforcement matches GreenSentinel's HITL rule. The payment signals themselves are out of scope. |
| [Risk Entity Watch](https://www.uber.com/us/en/blog/risk-entity-watch/) | Entity-level anomaly detection over riders, drivers, payment methods, emails, cities, devices. Features over **6 h, 7 d, 30 d** windows, for example `number_of_trips`. Time-series normalisation per entity; HAIFA histogram explanations for reviewers. Lists GPS spoofing and driver–rider collusion among fraud types. Model families are "tree-based to neural net-based"; specific models are not named. | Compare a driver with their own history, not only with fixed thresholds. Explanations must name the deviating feature. That fits our `reason_codes` and analyst brief. |
| [Rethinking GPS](https://www.uber.com/us/en/blog/rethinking-gps/) | In dense cities GPS error can be "50 meters or more" (urban canyons, reflections). Uses per-satellite SNR from Android plus 3D maps to infer the side of the street. No quantitative improvement figures are published in the post. | A 50 m error is ordinary in cities, so it must not be read as fraud. It supports capping the SSD anchor radius at 50 m and treating large accuracy values as quality evidence. |
| [Beacon: improving pickups with better location accuracy](https://www.uber.com/us/en/blog/beacon-improving-pickups-with-better-location-accuracy/) | Dashboard hardware with GNSS, IMU (accelerometer, gyroscope), and barometer for sensor fusion. In urban canyons GNSS error can exceed **100 m**. About 95% of US driver phones have a gyroscope; about 60% have a barometer. | Pickup geometry is the noisiest moment of a trip. An arrival radius of 30 m can be missed by an honest driver in a canyon; distance-to-pickup evidence needs the accuracy context. |

## 2. Hypotheses and signals

"In FeatureWindow" refers to the PR #43 implementation. Tasks: DA-02 (features), DA-03 (guardrail), DA-06 (generator), "later" = a future sprint.

| # | Signal | How to compute | Fields needed | In FeatureWindow? | Task |
|---|---|---|---|---|---|
| 1 | Stall before pickup (ERR-02) | Longest anchored stationary chain before arrival | `occurred_at`, position, `accuracy_m`, pickup | Yes: `approach_stationary_duration_s` | DA-02; DA-06 must generate stalls outside 30 m and before arrival |
| 2 | Moving away from pickup (DAVI) | Distance-weighted cosine between merged displacement segments and the pickup direction | Ordered positions, pickup | Yes: `davi` | DA-02; the OSRM route version comes later |
| 3 | Mock location provider (ERR-05) | Share of points with `mock_location_reported` or `gps_state = mock_reported` | `mock_location_reported`, `gps_state` | Yes: `gps_quality.mock_ratio` (and mock points are excluded from geometry) | DA-02/DA-03 |
| 4 | Teleport / implausible kinematics | Segments whose derived speed exceeds 50 m/s | Positions, `occurred_at` | Yes: `speed.implausible_speed_segments` | DA-02; the threshold is a demo value and needs verification per vehicle type |
| 5 | Observation gaps and coverage | Largest interval; share of window covered by intervals ≤ 30 s | `occurred_at` of every ping | Yes: `max_gap_s`, `telemetry_coverage` | DA-02/DA-03; DA-06 must create real gaps for dropout scenarios |
| 6 | GPS accuracy context | p50/p95 accuracy and unknown share; OS-specific meaning (Posisi) | `accuracy_m`, **device platform** | Partly: `gps_quality.accuracy_p50_m/p95_m`; no device platform | Later (needs schema field) |
| 7 | Driver–passenger pair frequency (collusion) | Count trips per driver–passenger pair over 15 min / 1 h / 1 d windows (Trust Counter) | `driver_id`, `passenger_id`, trip history | No | Later |
| 8 | Driver deviation from own baseline | Per-driver rates (cancellations, stalls) over 6 h / 7 d / 30 d, compared with the driver's history (Risk Entity Watch) | Case and trip history per driver | No | Later |
| 9 | Route stretch versus cohort (ERR-02 detour) | Path length ÷ endpoint distance; MiPo shows detour outliers at median tortuosity 1.5622 versus 1.2769 for normal trips | Complete trajectory, cohort | No | Later |
| 10 | Urban-canyon accuracy inflation | Flag windows where accuracy > 50 m before interpreting SSD/DAVI | `accuracy_m` | Partly: the SSD anchor radius adapts up to 50 m | DA-03 follow-up; threshold needs verification |

## 3. What the sources do not establish

- No source publishes stall-duration, DAVI, or cancellation-rate distributions for honest versus fraudulent drivers. Every scenario threshold in GreenSentinel remains demo configuration.
- The Posisi paper shows interval and accuracy histograms as figures only. Exact percentiles (for example, the share of intervals above 30 s) **need verification** against the raw dataset.
- Neither Posisi nor Porto includes device health (`app_state`, `network_state`), mock-provider flags, or pickup coordinates.
- Uber's posts do not state which detectors catch GPS spoofing.

## 4. Out of scope this sprint

- Payment fraud, unpaid orders, chargebacks, and payment-time-series anomaly detection (RADAR).
- Device farms, account/device/IP graphs, graph neural networks, money laundering (Grab graph networks).
- Promotion abuse and rider–driver self-dealing counters that need a transaction ledger (Trust Counter, Mastermind).
- Account takeover and risk challenges.
- Sensor fusion (IMU, barometer), SNR/3D-map positioning, and dedicated hardware (Beacon, Rethinking GPS).
- Production rules-engine infrastructure and real-time actioning; GreenSentinel never auto-sanctions.
