# ADR-013: Jev Advisory Anomaly Scoring and Single-Trip Fraud Scope

## Status

Accepted

## Context

Issue #71 updates the requirements for the Jev Advisory Assessment Engine:
Jev assesses incoming cases based on rich multi-modal inputs:
- Driver profile (name, rating, total trips, acceptance/cancellation rates, status)
- Driver analytics (prior sanctions, dispute history, historical cancellation ratios)
- Trip conversation (in-trip chat between passenger and driver)
- Driver's reason and agent conversation (post-trip explanation, dispute dialogue)
- Customer reports (complaints, ratings, reported feedback)
- Telemetry & kinematic maneuvers (turn-by-turn trajectory, speed, stationary duration, GPS mock flags, platform health)
- Trip operational metadata (pickup/dropoff coordinates, fare, lifecycle status, cancellation actor/reason)

The model predicts the fraud error type, model confidence score, and automatically evaluates the case priority tier (`P0`, `P1`, `P2`) to triage cases in the analyst workspace UI.

## Decision

### 1. Multi-Layer Jev Assessment Architecture
We employ a two-layer decision architecture executed via OpenRouter's `/api/alpha/decisions` API using the `~typesafe/jev-latest` decision model, paired with an exact calibrated deterministic heuristic fallback:
- **Layer 1: Fraud Error Type Classification (`error_type`)**:
  - Classifies the case into `ERR-01` to `ERR-05`, `no_violation`, or `insufficient_evidence`.
  - Outputs calibrated decision choice, confidence score (`0.00` to `1.00`), and class probability distribution.
- **Layer 2: Autonomous Priority Tier Assessment (`priority_tier`)**:
  - Evaluates operational urgency and financial/safety risk into `P0`, `P1`, or `P2` with an associated priority score (`1` to `100`).
  - `P0`: Fake GPS (`ERR-05`), severe technical tampering, urgent risk requiring immediate intervention.
  - `P1`: Prolonged stalling (`ERR-02`), route divergence (`ERR-03`), ghost trips (`ERR-04`), passenger disputes requiring prioritized analyst investigation.
  - `P2`: Minor irregularities, driver cancellation (`ERR-01`), nominal low-risk monitoring, or unverified technical dropouts.

### 2. In-Scope: Single-Trip Fraud Types (ERR-01 to ERR-05)
The engine exclusively evaluates fraud patterns detectable within a single-trip boundary from kinematic, conversational, and transactional observables:

| Fraud Code | Description | Regulatory Reference | Primary Evidence Signals |
|---|---|---|---|
| **ERR-01** | Driver Unjustified Cancellation | Điều 14.1 Quy chế GreenSM 2026 | Unilateral driver cancellation without valid operational reason; refusal of dispatch. |
| **ERR-02** | Driver Stall Cancellation Fraud | Điều 14.2 Quy chế GreenSM 2026 | Vehicle stationary duration $\ge 180\text{s}$ near pickup inducing passenger to cancel; nominal traffic. |
| **ERR-03** | Route Detour / Wrong Direction | Điều 16.1 Quy chế GreenSM 2026 | Kinematic trajectory diverging from pickup; route length exceeds OSRM benchmark by $> 35\%$. |
| **ERR-04** | Ghost Ride Fraud | Điều 15.1 Quy chế GreenSM 2026 | Trip marked completed without passenger pickup or kinematic transit. |
| **ERR-05** | GPS Mocking & Telemetric Tampering | Điều 15.3 Quy chế GreenSM 2026 | Mock location API provider flag (`mock_location_reported`), velocity jumps $> 120\text{ km/h}$, spoofing. |

Technical dropouts (platform outages, degraded GPS accuracy, missing telemetry points $< 2$) short-circuit to `insufficient_evidence` with `confidence: 0.0` as mandatory guardrails.

### 3. Explicitly Deferred / Out-of-Scope: Multi-Entity Graph & Network Fraud
The following fraud typologies are **explicitly excluded and deferred** from the single-trip Jev assessment engine:
- **Collusion Rings**: Coordinated rings of drivers and passengers generating fictitious rides to artificially harvest driver milestone bonuses.
- **Promo Farming & Voucher Harvesting**: Syndicated abuse of referral codes, signup coupons, or marketing subsidies across synthetic user clusters.
- **Multi-Account Device Sharing**: Driver syndicates rotating shared hardware or credential farming across device graphs.

#### Rationale for Deferral
Single-trip telemetry ingestion processes localized spatial-temporal event streams. Detecting multi-entity graph fraud requires:
1. Cross-trip bipartite graph projections ($U \times D$ graphs of passengers and drivers).
2. Graph Neural Networks (GNNs) or community detection algorithms (e.g., Louvain, Leiden, PageRank-based clustering).
3. Cross-session historical graph data lakes (Neo4j, Amazon Neptune, or graph analytics in Spark/GraphX).
Attempting to classify network collusion on a single-trip telemetry payload produces high false-positive rates and lacks structural validity. These mechanisms belong to a dedicated offline graph analytics pipeline.

### 4. UI Surfacing Contract
- **Triage Queue (Left Sidebar)**: Each case item displays its designated error code badge (e.g., `ERR-02`) and percentage confidence (e.g., `92% Jev`).
- **Detail Workspace (Center Panel)**: A dedicated `Jev AI Assessment` banner displays:
  - Error type badge (e.g., `ERR-02`, `ERR-05`, `no_violation`)
  - Confidence percentage gauge with color coding ($\ge 90\%$ emerald, $\ge 70\%$ amber, $< 70\%$ slate)
  - Priority badge (`Priority: P0`, `Priority: P1`, `Priority: P2`)
  - Observable telemetry and kinematic signal tags (`stationary_duration_over_180s`, `mock_location_api_detected`, etc.)

## Consequences
- Single-trip telemetry assessments remain bounded, explainable, and reproducible.
- Model decisions are paired with calibrated fallback heuristics ensuring high system availability if OpenRouter experiences transient latency or outages.
- Clear separation of concerns between single-trip kinematic fraud (in-scope) and multi-trip graph collusion (deferred).
