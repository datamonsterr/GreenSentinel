# MiPo: GPS Fraud Evidence and Benchmark Design

**Research date:** 2026-09-23. **Scope:** research evidence and recommended evaluation protocol; measured results belong in the accompanying EDA artifacts. Business requirements: [PRD](../ba/PRD.md). Contract: [telemetry event schema](../architecture/schemas/telemetry-event.schema.json).

## 1. Dataset identity and provenance

MiPo means **middle polar coordinates**, a trajectory feature extraction method. The authors' repository distributes code and twelve derived benchmark variants. The paper distinguishes injected detours, perturbations, route switches, and manually labeled organic trajectory outliers. These labels describe trajectory abnormality; they do not establish a driver's intent or an adjudicated platform violation. [MiPo paper](https://doi.org/10.3390/rs14215394), [author repository](https://github.com/TimeIsAFriend/trajectory_MiPo), [benchmark directories](https://github.com/TimeIsAFriend/trajectory_MiPo/tree/main/dataset).

The underlying Porto resource at UCI documents 1,710,671 completed trips from 442 taxis. Its nine fields include identifiers, trip start time, missingness, and WGS84 `[longitude, latitude]` polylines nominally sampled every 15 seconds. UCI warns that `DAYTYPE` was calculated incorrectly. Its current dataset page specifies **CC BY 4.0**. This supports attribution-based use of that UCI resource, but does not establish a license for every derived artifact or implementation. [UCI dataset and license](https://archive.ics.uci.edu/dataset/339/taxi%2B).

The inspected MiPo repository root exposes no license file or license declaration. Record the downloaded commit and checksums, preserve attribution, and record its code/derived-artifact license as **unspecified** unless independently established. A paper's publication license is not evidence of an accompanying software license. The repository also has no packaged release in the inspected page. [Author repository](https://github.com/TimeIsAFriend/trajectory_MiPo).

Keep three inventories distinct:

| Artifact | Evidence carried | Permissible experiment claim |
|---|---|---|
| Porto source trips | Movement geometry, nominal sampling, source metadata | Geographic and kinematic profiling, subject to missingness |
| MiPo benchmark variants | Geometry plus organic/injected outlier labels | Detection of the supplied outlier definitions |
| GreenSentinel augmented replay | Source geometry plus explicitly generated operational context | Software behavior on a simulation with declared assumptions |

## 2. What GPS evidence can establish

An unusual route is an observation. A violation is a conclusion requiring a policy, operational context, and review. The same route may reflect congestion, legal turn restrictions, roadworks, passenger instructions, a mapping error, GPS noise, or deliberate abuse.

This distinction follows established trajectory research: iBAT groups routes by origin/destination and detects rare paths, while discussing both taxi detours and road network changes as applications. Therefore its anomaly score alone does not resolve the cause. [iBAT author paper](https://www-public.imtbs-tsp.eu/~zhang_da/pub/ibat-ubicomp11.pdf).

The following matrix is **GreenSentinel's proposed evidence model**, derived from the PRD and the available data; it is not a claim that MiPo contains these violations.

| PRD class | Signal we can investigate | Additional evidence needed | What MiPo can support | Main alternative explanation |
|---|---|---|---|---|
| **ERR-01: Trip/order embezzlement** | Travel continuing after an on-platform cancellation | Cancellation actor/time, assignment, passenger co-movement or statement, payment/receipt evidence, policy context | Geometry for a simulated investigation; no direct embezzlement label | Unrelated next trip, repositioning, an agreed cancellation |
| **ERR-02: Route deviation** | Rare path, looping, excess distance, sustained movement away from a target | Known target and lifecycle phase, road graph/profile, alternatives, traffic and passenger instructions | Strongest fit: compare geometry detectors on labeled route anomalies | Necessary detour, valid alternative route, map change |
| **ERR-02: Induced cancellation / stalling** | Sustained low progress or stationarity during an active pickup assignment | Assignment and pickup coordinates, reliable time, cancellation lifecycle, traffic/context, passenger reports | Feature prototyping and injected scenarios only; completed-trip geometry does not identify pickup behavior | Red light, congestion, safe waiting, pickup access restrictions |
| **ERR-03: Incentive/policy exploitation** | Repeated unusual short routes or recurrent account pairings | Incentive rules/version, booking/payment ledger, stable account/device links, repeated events | Route summaries as one input after enrichment | Legitimate commuting, common routes, promotions used correctly |
| **ERR-04: Phantom/virtual trips** | Implausible movement, identical replay, conflicting tracks | Independent passenger/device/network evidence, booking/payment records, adjudicated outcomes | Synthetic corruption checks and trajectory similarity; no proof of physical presence | Quantized coordinates, repeated route, stationary legitimate service |
| **ERR-05: Fake GPS / technological manipulation** | Coordinate jumps, improbable kinematics, route replay, sensor conflicts | Observed device integrity/mock-provider signals, accuracy, monotonic clock, independent location/motion corroboration | Anomaly candidates and injected robustness tests; no spoofing attribution | Multipath, stale fix, missing ping, clock error, map mismatch |

Graph evidence becomes necessary for coordinated abuse. Grab describes account/device/IP connections and network structure in its production fraud investigations. MiPo geometry alone cannot reproduce those account relationships. Treat graph models as a later experiment requiring an appropriately governed transaction dataset. [Grab Engineering](https://engineering.grab.com/graph-networks).

## 3. Detector candidates and constraints

| Candidate | Required input | Useful experiment | Constraint |
|---|---|---|---|
| Length/direct-distance ratio | Ordered positions with valid endpoints | Simple detour ranking baseline | Undefined or unstable when endpoint separation approaches zero; cannot distinguish legitimate route geometry |
| MiPo features + LOF | Trajectory geometry, cohort, specified endpoints and bins | Offline route-outlier ranking | Full endpoints cannot be taken from the future in live scoring; geometry alone lacks intent |
| MiPo features + Isolation Forest | Same geometry features | Compare a different detector at fixed feature representation | Fit only on training data for held-out evaluation; report seed sensitivity |
| Origin/destination route rarity | Adequate historical trips in the same cohort | Identify deviations relative to comparable journeys | Sparse cohorts and emerging valid routes require abstention |
| Stationary duration / progress | Timestamped pings and pickup target | Controlled pickup-delay scenarios | Missing time or pickup makes the operational metric unavailable |
| Speed/jump rules | Trustworthy times and distance calculations | Corruption screening and uncertainty analysis | Kinematic anomalies are not confirmation of spoofing |
| Map-matched route excess | Raw pings, frozen map/profile, matching confidence, route alternatives | Assess deviation relative to a documented route model | A matching failure can be a data/map problem; profile differences change routes |

OSRM's route service finds a fastest route for its profile, rather than guaranteeing the shortest distance. Its match service can split traces and remove unmatched points; outputs include matching confidence. Retain raw pings and rejected-point counts so preprocessing does not erase the evidence under investigation. Freeze the map date and routing profile for reproducibility. [OSRM API](https://project-osrm.org/docs/v5.24.0/api/).

### Timing and uncertainty

For a complete Porto sequence, nominal replay time can be derived from the documented start time and 15-second cadence. Mark this time as derived. A missing-point flag does not identify the position of each gap. A MiPo artifact that omits absolute time cannot establish a real occurrence timestamp merely by retaining point order.

Suggested feature definitions for a future timestamped dataset:

- Segment speed: geodesic distance divided by positive elapsed time; return unknown for invalid time.
- Stationary duration: sum valid consecutive intervals satisfying an explicitly versioned displacement/speed criterion. Break accumulation across excessive gaps.
- Direction relative to pickup: cosine similarity between displacement and the current-to-pickup vector. Return unknown for zero displacement or a near-zero target vector.
- Progress rate: decrease in distance to pickup per valid elapsed time. Compare road-network progress where feasible.

These are analysis proposals, not calibrated GreenSM thresholds. A fixed five-metre displacement threshold is not reliable proof of stationarity without a model of location uncertainty.

Android documents horizontal accuracy as a 68th-percentile radius, `isMock()` as a reported mock-location marker, and monotonic elapsed realtime for comparing fixes. It also distinguishes reported speed from speed calculated through position differences. Preserve these meanings; a missing mock marker is unknown, and a false marker is not independent proof of authenticity. [Android Location API](https://developer.android.com/reference/android/location/Location).

## 4. Benchmark protocol

### A. Published results are reference values

The MiPo paper reports mean ROC-AUC **0.99** for MiPo+LOF over its twelve variants. Its Table 2 ranges from **0.97 to 1.00**. These are published results on that experimental setup; they do not establish production fraud accuracy, DIC precision, or local runtime. [MiPo results, Table 2](https://doi.org/10.3390/rs14215394).

iBAT reports AUC above 0.99 in its own taxi experiments. A separate e-hailing detour paper reports offline AUC above 0.98 and online AUC above 0.90. Different data, annotation, splits, and metrics prevent a direct leaderboard comparison. These works motivate offline/online evaluation as separate tasks. [iBAT](https://www-public.imtbs-tsp.eu/~zhang_da/pub/ibat-ubicomp11.pdf), [Tian et al.](https://arxiv.org/abs/1910.06949v3).

### B. Local experiments must state the evaluated task

| Evaluation track | Unit and label | Required outputs | Claim allowed |
|---|---|---|---|
| Published-artifact ranking | Whole trajectory; supplied label | Per-variant ROC-AUC, average precision, class counts, feature and scoring time | Agreement with provided trajectory labels |
| Held-out trajectory detection | Independent source trajectory group | ROC-AUC, average precision, precision at review budget, fixed-threshold recall, grouped uncertainty interval | Generalization to held-out trajectories under the declared split |
| Simulated operational detection | Generated case with documented injection | Recall by injection, alert delay, benign-control alert rate, abstention rate | Response to modeled failures or abuse patterns |
| Target-domain validation | Adjudicated pickup case | Precision/recall by violation, safety errors, subgroup results, review outcomes | Evidence toward GreenSM deployment readiness |

Minimum local baseline set: route-length ratio, tabular geometry + LOF, MiPo + LOF, and MiPo + Isolation Forest. Keep identical records, labels, score polarity, and evaluation units across methods. If only some methods run, identify the remainder as proposed.

### C. Prevent leakage and misleading metrics

1. **Choose the claim first.** Whole-dataset LOF ranking is transductive; held-out novelty detection requires a distinct fit/predict protocol. Report them separately.
2. **Split related trajectories together.** Hash exact duplicates across variants. Use source-trip identity where available for modified variants. Exact hashing alone does not identify a perturbed copy.
3. **Do not pool variant files into a random row split.** Related normal and modified trips may recur across scenarios. If source identity is unavailable, run each variant independently and disclose unresolved near-duplicate leakage risk.
4. **Fit transformations on training data.** Scaling, feature selection, contamination thresholds, and parameter choices must not use test labels. A reproduction-style transductive run must state its exception explicitly.
5. **Avoid endpoint leakage in pickup scoring.** A destination supplied by the booking is usable if known at scoring time. The final observed coordinate of a completed trace is future evidence. Truncating a route while retaining its actual final endpoint does not demonstrate live DIC capability.
6. **Report prevalence.** Average precision's random baseline equals the positive fraction. Precision changes with prevalence even when the conditional error rates remain similar.
7. **Attach uncertainty.** Use grouped bootstrap intervals where independent groups exist. Few positives require wide uncertainty statements; a high AUC on one small cohort is insufficient for enforcement.
8. **Keep signal quality visible.** Stratify by path length, point count, duplicate fraction, missingness, geography, and label origin. Report abstentions and excluded counts.
9. **Version everything.** Archive source commit/checksums, cohort construction, seeds, library versions, operating system, CPU, thread settings, map version, and policy parameters.

### D. Operational benchmarking

Measure parsing, feature extraction, model fitting, batch scoring, per-case scoring, schema validation, and serialization separately. Report repeat count, warm/cold state, batch size, p50/p95 latency, peak memory, and trajectories/second. A microbenchmark cannot establish the PRD's end-to-end two-second detection requirement without event transport and application processing.

Evaluate a review budget, such as top 20 cases per 1,000 trips, alongside AUC. This is a proposed experimental operating point, not a deployment target. For synthetic pickup scenarios, measure event-time delay from injection onset and wall-clock processing latency separately.

The PRD's false alarm ratio concerns wrongly penalized drivers overturned on review. That differs from classifier false positive rate, `FP / (FP + TN)`, and false discovery proportion, `FP / (TP + FP)`. Report all applicable denominators explicitly. MiPo labels cannot measure overturn rate, passenger churn, pickup completion uplift, or analyst handling time; those require product or adjudication studies.

## 5. Implications for the telemetry contract

The existing contract requires event/assignment/driver identifiers, occurrence time, and accuracy. Geometry-only artifacts do not supply all of these facts. Required fields should not induce fabricated evidence.

Recommended semantics for the schema integration:

- Preserve real coordinates and source point order. Keep coordinate order conversion explicit.
- Permit unknown accuracy when absent; do not substitute zero or a fabricated precision.
- Distinguish observed, derived, and simulated fields through provenance. Keep source artifact/record references and transformation version.
- Keep app/network/GPS state `unknown` unless supported. Leave mock-provider flags and operational metrics null when unavailable.
- Give deterministic import IDs a namespace and provenance. An import-generated driver or assignment ID does not demonstrate a real driver or dispatch relationship.
- Give replay clocks explicit simulation provenance. Keep geometry-only imports outside production evidence paths unless their missing operational context is represented.
- Preserve `dataset_label` separately from a policy verdict. Never map `outlier=1` directly to `ERR-02` or `ERR-05`.

The immediate product use is an analyst evidence prototype: render source geometry, show model scores and data limitations, and support human review. The most defensible scientific deliverable is a reproducible trajectory-outlier benchmark. Production DIC and spoofing claims require timestamped pickup data and independent operational evidence.
