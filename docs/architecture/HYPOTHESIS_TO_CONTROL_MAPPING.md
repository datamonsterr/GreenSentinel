# Analyst Hypothesis-to-Control Mapping Specification

## 1. Design Reference & Stitch Baseline
* **Stitch Design Project:** [Stitch Analyst Cockpit Workspace (P-063)](https://stitch.withgoogle.com/projects/p-063-analyst-cockpit)
* **Functional Scope:** Sprint 2 Feature `[S2-F02] Compact analyst cockpit decision workspace` (Issue #59).
* **Core Standard:** Strict HITL decisioning per [`PRD.md`](../ba/PRD.md) and [`US-L06-04`](../ba/USER_STORIES.md#us-l06-04--decide-an-initial-enforcement-case-phase-1-mvp-core). Every dismissal and adverse sanction requires authorized human sign-off with mandatory written rationale ($\ge 10$ characters). No fabricated evidence; missing sources display as `N/A / Unavailable`.

---

## 2. Hypothesis to UI Control & Evidence Mapping Matrix

| Analyst Hypothesis | Decision-Critical Evidence | UI Control / Viewport | Backing Data Source | Missingness Behavior | Permitted HITL Actions |
|---|---|---|---|---|---|
| **H1: Intentional Stalling (DIC)**<br>Driver deliberately halted to induce passenger cancellation. | • Stationary dwell duration ($\ge 180$s threshold)<br>• Kinematic velocity ($v = 0$ m/s)<br>• Distance to pickup | • `OverviewTab` → Kinematic Telemetry pill (`{stall_duration_s}s`)<br>• `MapLibreView` → Vehicle stall marker | `app.telemetry_points`<br>`app.feature_sets.stationary_duration_s` | Explicit `Stall: N/A`<br>No mock 420s fallback | • **Approve:** Sanction confirmed ($\ge 10$ chars rationale)<br>• **Request:** Seek explanation |
| **H2: Objective Gridlock**<br>Delay caused by traffic congestion rather than driver bad faith. | • Corridor ambient speed vs OSRM baseline<br>• Speed ratio $< 0.7$<br>• Peer driver speed probes | • `OverviewTab` → `Traffic Gridlock Assessment` toggle box<br>• Speed ratio comparison bar | `app.traffic_corroboration`<br>TomTom / OSRM corridor probe | Explicit `Chưa có thông tin hành lang`<br>Peer count shows actual `0` | • **Dismiss:** False alarm due to gridlock<br>• **Request:** Check driver statement |
| **H3: Location Spoofing**<br>Driver used Mock Location app or GPS emulator. | • `mock_location_reported` flag<br>• GPS accuracy variance ($> 15$m)<br>• Jump vector without road network binding | • `OverviewTab` → `Platform & Sensor Reliability` toggle box<br>• `Mock: Detected` / `Mock: Clean` badge | `app.telemetry_points.mock_location_reported`<br>`app.telemetry_points.gps_accuracy_m` | Explicit `GPS: N/A`<br>Mock flag `false` by default | • **Approve:** Fraud verified<br>• **Escalate:** Senior lead review |
| **H4: Telemetry Dropout / App Crash**<br>Missing data caused by system error or network loss. | • Telemetry gap duration alerts<br>• App state `crashed` signal<br>• Ping latency & battery level | • `OverviewTab` → Signal Gap indicator<br>• Guardrail blocking notice<br>• Channel 2 (Ping) & Channel 3 (Battery) | `app.missingness_alerts`<br>`app.guardrails` blocking state | Explicit `Chưa có dữ liệu`<br>Guardrail blocks all adverse sanctions | • **Dismiss:** System error confirmed<br>• Approve is **HARD-LOCKED** by guardrail |
| **H5: DAVI Route Deviation**<br>Driver drove away from passenger destination deliberately. | • Directional Angle Velocity Index (DAVI)<br>• Reverse vector away from pickup<br>• Drift deviation distance | • `OverviewTab` → `DAVI {score}` badge<br>• `MapLibreView` route geometry overlay | `app.telemetry_samples.davi_score`<br>`app.feature_sets.davi_score` | Explicit `DAVI: N/A`<br>Drift: `Chưa ghi nhận` | • **Approve:** Intentional deviation<br>• **Request:** Clarify detour route |

---

## 3. UI State Lifecycle Handling

1. **Loading State:** `CockpitWorkspaceView` displays accessible skeleton status (`Loading cockpit workspace`) while fetching queue and initial case details.
2. **Empty State:** When no active case or queue item is available, renders informative `No available cases` with an explicit `Retry` control.
3. **Missing Evidence State:** When sensor, traffic, or feature samples are absent, metrics display `N/A`, `Unavailable`, or `Chưa ghi nhận`. The frontend strictly avoids inventing fallback numbers.
4. **Failure State:** Network errors and 5xx API outages render inline retryable alert notices (`role="alert"`), keeping previously fetched context intact without optimistic overwrites.
5. **Read-Only Lock State:** When an analyst accesses a case claimed by another peer, the case is placed in read-only lock (`isLockedByOther = true`). The claim button renders `Locked by another analyst` and decision actions are disabled.

---

## 4. HITL Decision Enforcement Rules
* **No Auto-Dismissal:** All case closures require human submission.
* **Mandatory Rationale:** Both client form and server API schema (`AdjudicationRequest`) reject rationale strings under 10 non-whitespace characters (`min_length=10`).
* **RBAC Restrictions:** Unauthorized roles (`driver`, `passenger`, `guest`, `unauthorized`) cannot adjudicate. Actions execute with append-only audit persistence recording analyst identity, case version, rationale, and timestamp.
