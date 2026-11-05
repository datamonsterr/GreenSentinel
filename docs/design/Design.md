# GreenSentinel — UI/UX Design System Specification

> **Design System:** Emerald Sentinel v2.0 · **Architecture Standard:** Compact Technical Modernism  
> **Target Applications:** Workplace Cockpit (`/workplace`), Driver Care Portal (`/driver`), Tester Trip Studio (`/test`)  
> **Source Repository:** GreenSentinel (VinUni AI20K Build Phase) · **Last Updated:** 2026-10-05  
> **Stitch MCP Projects:**  
> • Cockpit & Fleet Workstation: [`projects/12095025610159108305`](https://stitchdesign.google.com/project/12095025610159108305)  
> • Tester Simulation Studio: [`projects/7541683500450336068`](https://stitchdesign.google.com/project/7541683500450336068)  
> • Tactical GIS Telemetry: [`projects/7784297700642891517`](https://stitchdesign.google.com/project/7784297700642891517)  

---

## 1. Master Design Principles

This design system governs all user interfaces across Project GreenSentinel. The interface serves fraud analysts, operations supervisors, partner drivers, and automated test engineers who require high-frequency decision making, rapid telemetry inspection, and zero cognitive clutter.

### Rule 1: Visual Icon & Layout Primacy (Zero Verbose Text Explanations)
- **Eliminate conversational text explanations** from operational views. Analysts use this system continuously during full shifts; wordy explanations increase cognitive load and latency.
- Prioritize universally recognized symbols (Material Symbols Outlined / Lucide), standardized layout positions, and deliberate color signals to communicate next actions and state.
- **Example:** Replace text like `"Settings"` or `"Open System Settings"` with `<span className="material-symbols-outlined">settings</span>` accompanied by an accessible `aria-label="Settings"` and lightweight hover tooltip.
- Buttons present action verbs or concise states (`Save`, `Run`, `Apply`, `Dismiss`); helper tips remain tucked inside interactive tooltips (`help_outline` / `info`).

### Rule 2: Pure Symbolic Brand Identity (Strictly No Company Letters in Logos)
- **Zero letter-based brandmarks or company acronyms** anywhere in the application (no `"GS"`, `"G"`, `"V"`, `"SM"` letter avatars or textual logos).
- All brand marks, app switchers, and system headers must use pure vector geometry and domain-specific iconography:
  - App Launcher / Sentinel Root: Vector Shield (`security` / `shield`)
  - Driver Entity: Clean Vehicle / Steering (`directions_car` / `car_rental`)
  - Passenger / Customer Entity: Person Pin (`person` / `account_circle`)
  - Bot / AI Agent: Friendly Bot / Assistant (`smart_toy` / `support_agent`)
  - GIS Telemetry: Geospatial Route (`route` / `satellite_alt`)

### Rule 3: Compact Technical Modernism (Minimal UI/UX Style)
- Clean, utilitarian, high-density analytical HUD aesthetics.
- **1px hairline borders** (`#d8e1dd` / `border-outline-variant/60`) define panel boundaries without heavy dropped shadows.
- Generous, disciplined data-to-ink ratio: eliminate decorative gradients, heavy rounded corners, and excessive empty padding.
- Crisp structural surfaces: cool ice-white canvas (`#f8f9ff`), pure white modular panels (`#ffffff`), and high-contrast navy typography (`#0b1c30`).

### Rule 4: Workplace Cockpit Principle (Speed & Analytics Over Hand-Holding)
- Built for real-time adjudication of Driver Incentive Cheating (DIC) with **Mean Time to Resolution (MTTR) < 45 seconds**.
- Core triage metrics appear at a glance without navigational friction:
  - Multi-tab center panel: `Overview` (GIS + Telemetry), `Conversation` (Dispute Statements), `Driver Information` (Dossier & History), and `Workflow Synthesis` (LangGraph Stepper).
  - 4x1 Collapsible Toggle Boxes in Overview: `Violation Detection`, `Traffic Gridlock Assessment`, `Platform & Sensor Reliability`, and `Stall & Drift Telemetry`.
- **Zero Duplicated Content:** A data point (e.g. driver speed or cancellation timestamp) is presented authoritatively in its primary analytical widget, never cloned verbatim across separate tabs.
- **Behavioral Click Logging:** Capture analyst interaction events (e.g. toggle expansions, tab switches, map zoom, evidence inspection duration) as high-value implicit feedback for offline policy optimization and agent reinforcement.

### Rule 5: Driver Care Console (Friendly AI Agent with Clear Micro-Interactions)
- The Driver Dispute interface (`/driver`) is a dedicated desktop operations console balancing professional authority with an approachable, supportive user experience.
- AI Assistant utilizes a friendly chatbot icon (`smart_toy` / `support_agent`) rather than corporate acronyms.
- **Clear animated feedback:**
  - Active streaming & thinking states: pulsating status dot (`animate-pulse`) and animated typing indicator (`animate-bounce`).
  - Smooth card transitions when submitting quick dispute claims or uploading supplemental proof.
  - Distinct visual separation between AI advice, policy excerpts, and automated confirmation receipts.

### Console Architecture Standard (Strictly Desktop Console — Zero Mobile App Target)
- All user interfaces across Project GreenSentinel are **desktop workstation consoles** exclusively (designed for 1280px to 1920px+ monitors).
- There is **no mobile application** and no mobile phone layout target.
- Mobile-first stacking, collapsible drawer workarounds for phone screens, and small-touch compromises are strictly prohibited. Multi-pane simultaneous visibility (actor rail, map stage, tools panel) is required at all times.

### Rule 6: Tester Console (Trip Studio Follows Workspace Principles)
- The Tester Studio (`/test`) is an operational test workbench, sharing the design tokens and component standards of the Workplace Cockpit.
- **3-Column Composition:**
  - **Left Rail (264px):** Simulated Actors — Driver Window stacked directly above Passenger Window. Each window contains notification inbox items, conversation transcript, and role-scoped reply composer.
  - **Center Stage (Flexible):** Interactive Map Editor (origin, pickup, destination endpoints, road route candidates, deliberate fault visualization), playback scrubber timeline, and kinematic metrics strip.
  - **Bottom Center:** Actual System Results Panel displaying consumed event streams, detection outputs, and direct links to generated cases in Workplace.
  - **Right Rail (300px):** Simulation Tools Panel with tabbed controls (`Trip`, `Traffic`, `Faults`), live plan validation summary, and execution actions.

### Rule 7: Refined Color Palette ("Emerald Sentinel 2.0")
- Functional color signaling ensures instant, unambiguous situational awareness across all lighting conditions.
- Every color maps directly to an operational semantic meaning (see Section 2 for the complete palette).

### Rule 8: Unified Component Architecture (shadcn/ui + Domain Primitives)
- Built on top of Radix UI primitives and Tailwind CSS (`@tailwindcss/postcss`).
- Common reusable components:
  - `Button` (`@/components/ui/button`): Compact 28px/36px heights, outline/ghost/primary variants.
  - `Badge` (`@/components/ui/badge`): Single-line status indicators with semantic background/text pairs.
  - `Card` (`@/components/ui/card`): 1px bordered containers with sharp or 6px radius.
  - `Skeleton` (`@/components/ui/skeleton`): Shimmer placeholders for loading states.
  - `ChatWidgets` (`@/components/ui/chat-widgets`): Structured citation cards, tool call accordions, and markdown blocks.
  - `MapLibreView` (`@/components/map/maplibre-view`): High-performance vector map with route polylines and animated markers.

### Rule 9: Ubiquitous Skeleton Loading States
- Every asynchronous surface, data table, chat stream, and telemetry card MUST provide a dedicated skeleton state.
- **Zero layout shifts:** Skeleton containers must exactly match the height, width, and padding of the incoming hydrated component (`WorkspaceInitSkeleton`, `CockpitWorkspaceSkeleton`, `CockpitDetailSkeleton`, `CockpitChatSkeleton`, `TesterStudioSkeleton`).
- Never show blank screens, bouncing spinners that displace layout, or abrupt flashes of unstyled content.

### Rule 10: Strict Anti-Wrap & Single-Line Discipline
- **Zero text breakdown / wrapping** on controls and metadata:
  - **Buttons:** Enforce `whitespace-nowrap inline-flex items-center shrink-0` across all action triggers.
  - **Badges, Tags, Pills:** Strictly single-line (`whitespace-nowrap shrink-0 max-w-full truncate`).
  - **Table Headers & Metric Labels:** Single-line captions with overflow truncation and tooltip fallback.
  - **Grid & Flex Containers:** Specify explicit `min-w-0` and proportional flex bounds to prevent accidental line wraps in dense workstation viewports.

---

## 2. Refined Color System ("Emerald Sentinel 2.0")

The color palette is engineered for high-density analytical displays, adhering to strict WCAG 2.1 AAA contrast ratios for body and tabular data.

### 2.1 Foundation & Surfaces

| Token | Hex Value | Tailwind Class | Semantic Usage |
|---|---|---|---|
| `surface` | `#f8f9ff` | `bg-surface` / `bg-slate-50` | Primary viewport canvas background |
| `surface-card` | `#ffffff` | `bg-white` / `bg-surface-container-lowest` | Elevated panels, cards, actor windows |
| `surface-subtle` | `#eff4ff` | `bg-slate-100` / `bg-surface-container-low` | Inactive tabs, hover states, recessed wells |
| `border-subtle` | `#d8e1dd` | `border-outline-variant/60` | 1px global partition lines and card perimeters |
| `border-active` | `#006948` | `border-primary` | Active selection, focused control rings |
| `on-surface` | `#0b1c30` | `text-foreground` / `text-slate-900` | Primary typography, high-emphasis metrics |
| `on-surface-variant` | `#3d4a42` | `text-slate-700` | Section subtitles, form labels |
| `secondary` | `#565e74` | `text-secondary` / `text-slate-500` | Timestamps, coordinates, helper captions |

### 2.2 Semantic & Operational Accents

| Token | Hex (Base / Fill) | Text / Border | Operational Signal |
|---|---|---|---|
| **Primary (Emerald)** | `#006948` (Solid) <br> `#e3f2eb` (Subtle) | `#ffffff` (On Primary) <br> `#006948` (Text) | Validated plan, primary action button, verified sensor status, active trip polyline |
| **Warning (Amber)** | `#d97706` (Solid) <br> `#fffbeb` (Subtle) | `#ffffff` (On Warning) <br> `#b45309` (Text) | P1 Warning anomaly, stall zone alert, traffic gridlock indicator, high latency drift |
| **Error (Crimson)** | `#ba1a1a` (Solid) <br> `#fef2f2` (Subtle) | `#ffffff` (On Error) <br> `#dc2626` (Text) | P0 Critical fraud, deliberate GPS fault, hardware dropout, sanction action, SLA breach |
| **Tertiary (Cobalt)** | `#0058be` (Solid) <br> `#edf3fc` (Subtle) | `#ffffff` (On Tertiary) <br> `#1d4ed8` (Text) | Passenger identity, pickup waypoint, geofence radius buffer, informational notification |
| **Muted Neutral** | `#64748b` (Solid) <br> `#f1f5f9` (Subtle) | `#334155` (Text) <br> `#cbd5e1` (Border) | Baseline speed comparison, inactive waypoint, system breadcrumb trail |

### 2.3 Priority Severity Standards

| Level | Background | Text Color | Border Color | Typical Violation Context |
|---|---|---|---|---|
| **P0 Critical** | `#fef2f2` (`bg-red-50`) | `#dc2626` (`text-red-600`) | `#fecaca` (`border-red-200`) | Active DIC, phantom trip, fake GPS mock location, verified incentive theft |
| **P1 Warning** | `#fffbeb` (`bg-amber-50`) | `#d97706` (`text-amber-600`) | `#fde68a` (`border-amber-200`) | Prolonged route deviation, uncorroborated stationary stall, suspect telemetry jitter |
| **P2 Notice** | `#eff6ff` (`bg-blue-50`) | `#2563EB` (`text-blue-600`) | `#bfdbfe` (`border-blue-200`) | Minor schedule delay, high ambient traffic corroboration, missingness guardrail pass |

---

## 3. Typographic Hierarchy

Typography enforces strict tabular alignment, immediate visual hierarchy, and zero layout shifting during high-speed telemetry streaming.

| Style | Font Family | Size | Weight | Line Height | Tracking | Use Case |
|---|---|---|---|---|---|---|
| `display-lg` | Inter | 20px | 700 | 24px | `-0.02em` | Main application titles (`Trip Studio`, `Cockpit`) |
| `headline-md` | Inter | 14px | 600 | 18px | `-0.01em` | Panel titles, tool tab headers, modal titles |
| `headline-sm` | Inter | 12px | 600 | 16px | `0` | Card section titles, toggle group headers |
| `body-md` | Inter | 12px | 400 | 16px | `0` | Dialogue text, forensic notes, policy clauses |
| `body-sm` | Inter | 11px | 400 | 14px | `0` | Metadata labels, secondary descriptions |
| `label-caps` | Inter | 10px | 600 | 12px | `0.04em` | Single-line tags, uppercase status chips |
| `code-md` | JetBrains Mono | 12px | 500 | 16px | `0` | Numeric telemetry readouts, speeds, distances |
| `code-sm` | JetBrains Mono | 10px | 400 | 14px | `0` | Lat/Long coordinates, case tokens, event IDs |

---

## 4. Workstation Architecture & Primary Views

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ GLOBAL HEADER: Shield Icon (No letters) · App Switcher · Ctrl+K Quick Search · Settings Icon · User Profile │
├────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ VIEWPORT WORKBENCH (Switched by Route or Top Navigation):                                              │
│                                                                                                        │
│  [1] ADJUDICATION COCKPIT (/workplace)                                                                 │
│      ├── Left Pane (22%): Priority Case Queue (P0/P1/P2, SLA timers, single-line tags)                 │
│      ├── Center Pane (52%): 4-Tab Center Panel + 4x1 Expandable Toggles + GIS Map + Sanction Bar       │
│      └── Right Pane (26%): LangGraph Policy Copilot + RAG Chat Stream + One-Click Citations            │
│                                                                                                        │
│  [2] TESTER TRIP STUDIO (/test)                                                                        │
│      ├── Left Rail (264px): Simulated Actors (Driver Window stacked above Passenger Window)           │
│      ├── Center Stage (Flex): MapLibre Editor + Scrubber Timeline + Kinematic Telemetry Strip          │
│      ├── Bottom Center: Actual System Results (Event timeline, Consumed states, Workplace Link)       │
│      └── Right Rail (300px): Simulation Tools Panel (Trip Params, Traffic Overrides, Deliberate Faults)│
│                                                                                                        │
│  [3] FLEET ANALYTICS DASHBOARD (/workplace?tab=analytics)                                             │
│      └── Operational KPIs (MTTR, HITL ratio, Ingestion vs Clearance, Spatial Gridlock Hotspots)        │
│                                                                                                        │
│  [4] ANALYST PROFILE & AUDIT LEDGER (/workplace?tab=profile)                                           │
│      └── Identity Header, Active Review Lock Banner, 4-Card KPI Row, Governance Limits, Audit Trail     │
│                                                                                                        │
│  [5] DRIVER DISPUTE CARE CONSOLE (/driver/dispute/[caseId])                                           │
│      └── Dedicated Operations Console (smart_toy avatar, quick claim chips, map telemetry stage)       │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 4.1 Adjudication Cockpit (`/workplace`)

- **3-Pane Operational Layout:**
  - **Left Triage Queue (22% width):** Ranked list of claimed and pending cases with color-coded severity borders, single-line vehicle plate/driver tags, and countdown SLA badges (`00:28 / 00:45s`).
  - **Center Case Workspace (52% width):**
    - **Header:** Case token, claim lock status, driver ID, vehicle plate, and current case version.
    - **4-Tab Navigation:**
      1. `Overview`: MapLibre GIS tracking, velocity timeline, and 4 expandable 4x1 toggle boxes (`Agent Violation Detection`, `Traffic Gridlock Assessment`, `Platform & Sensor Reliability`, `Stall & Drift Telemetry`).
      2. `Conversation`: Side-by-side statements (Driver statement vs Customer cancellation signal), Precedent Match card, and dispatch relay.
      3. `Driver Info`: Behavioral scorecard, vehicle inspection status, and 30-day violation history.
      4. `Workflow Synthesis`: Stepped LangGraph process ribbon, tool execution logs, and policy citations.
    - **One-Click Sanction Bar:** 6 compact single-line actions (`Dismiss`, `Request Info`, `Warn`, `Fine`, `Suspend 24h`, `Escalate`) with mandatory validation check and rationale box.
  - **Right Policy Copilot (26% width):** Real-time SSE streaming assistant, verified citation snippets, and quick analyst prompt pills. Supports explicit **Context Reset** checkbox (`FR-WS-01`).

### 4.2 Fleet Analytics Dashboard (`/workplace?tab=analytics`)

Operational intelligence view for senior analysts, shift supervisors, and operations managers.

#### KPI Banner (4 Cards)
1. **Mean Time to Resolution (MTTR):** Server-side aggregate duration across completed adjudications (`AC-MVP-05`). Displays `"N/A"` if no adjudications recorded.
2. **HITL Enforcement Ratio:** Percentage of cases adjudicated by human analysts vs autonomous flows (`100%` under strict Phase 1 policy).
3. **Active Backlog:** Live count of unassigned non-terminal cases across the organization.
4. **Daily Ingestion Volume:** Total alerts ingested in current 24h cycle.

#### Operational Panels
- **Hourly Ingestion vs Clearance:** Time-series comparison of incoming detector alerts vs completed adjudications.
- **Violation Breakdown:** Distribution across canonical taxonomy (`ERR-01` embezzlement, `ERR-02` DIC/route deviation, `ERR-03` incentive exploitation, `ERR-04` phantom trips, `ERR-05` sensor manipulation/fake GPS).
- **Spatial Gridlock Hotspots:** Aggregated geographic concentration of verified delays and sensor errors.
- **Adjudication Outcome Breakdown:** Distribution across human verdicts (`Dismissed`, `Warning`, `Fine`, `Suspension`).

### 4.3 Analyst Profile & Immutable Audit Ledger (`/workplace?tab=profile`)

Personal compliance and immutable activity record for the authenticated fraud analyst.

- **Header Section:** Analyst full name, Clerk ID, active organization ID, and role badge (`fraud_analyst`, `senior_analyst`, `manager`).
- **Active Review Lease Banner:** Dynamic countdown timer of remaining lease TTL (`mm:ss`) on currently locked case, with `"Resume Case →"` quick action.
- **4-Card Decision Metrics Row:**
  - `Today's Decisions`: Decisions committed within current UTC day.
  - `Average MTTR`: Mean elapsed seconds from lease acquisition to verdict submission.
  - `Quality & Overturn`: Measured overturn percentage against supervisory audit (renders `"N/A"` when benchmark data uncalibrated).
  - `30-Day Total`: Rolling 30-day adjudication volume.
- **Governance Limits Bar:** Explicit visual bounds on analyst authorities:
  - Dismiss Authority (`Unrestricted` or `Senior Only`)
  - Warning Authority (`Authorized`)
  - Direct Fine Limit (`≤ 2M VND` for junior, `≤ 10M VND` for senior)
  - Suspension Authority (`24h / 48h Lockout`)
  - Model Agreement Rate (renders `"N/A"` when benchmark unobserved)
- **Immutable Verdict Ledger Table:** Paginated, sortable record of historical adjudications with real-time text search (case ID, plate, driver) and verdict dropdown filtering.

### 4.4 Driver Dispute Care Console (`/driver/dispute/[caseId]`)

Dedicated desktop operations console for partner drivers to review detected anomalies and provide evidence.

- **Header:** Friendly Assistant icon (`smart_toy`), case code, and current lifecycle status (`driver_assistance`, `awaiting_driver_confirmation`).
- **Evidence-Grounded Summary:** Transparent explanation of suspected anomaly (route deviation, stationary duration) grounded in GPS telemetry.
- **Interactive Chat Stage:** Streaming conversation where driver explains circumstance or submits evidence.
- **Confirmation Step:** Clear choice prompt:
  - `"No further appeal"`: Closes case as **Driver confirmed resolution** (`FR-DF-03`).
  - `"Continue appeal"`: Escalates case directly to fraud Analyst triage queue (`FR-DF-03`).
- **Integrated Map View:** Synchronized MapLibre trajectory inspection allowing driver to verify location and traffic congestion.

### 4.5 Tester Trip Simulation Studio (`/test`)

The complete simulation console implementing PR #138 specification:

- **Top Application Bar:** Shield icon + `Trip Studio` + environment indicator (`Isolated test workspace`) + `Save Plan` + `Validate & Run` controls.
- **Left Actor Rail (264px):** Simulated Driver Window (top 50%) stacked above Simulated Passenger Window (bottom 50%).
- **Center Stage (Flexible):** Interactive MapLibre editor, playhead timeline scrubber (`00:00 / 02:45`), and kinematic metric strip (`Road Distance`, `ETA`, `DAVI Index`).
- **Bottom Center:** Actual System Results Panel displaying consumed event streams, detection outputs, and direct link to generated case in Workplace.
- **Right Tools Panel (300px):** Tabbed controls (`Trip`, `Traffic`, `Faults`), pre-flight validation summary, and execution actions.

---

## 5. Component & State Contracts

Every view strictly enforces 5 distinct operational states:

| State | Adjudication Cockpit (`/workplace`) | Fleet Analytics (`/analytics`) | Analyst Profile (`/profile`) | Driver Care (`/driver`) | Tester Studio (`/test`) |
|---|---|---|---|---|---|
| **Missing** | Disclose missing GPS/telemetry; disable Fine/Suspend if sensor reliability guardrail fails | Display `"N/A"` or `"—"` with tooltip explaining missingness; never invent zero values | Show `"N/A"` for unmeasured quality overturn or model agreement rates | Disclose unrecorded telemetry segments; allow driver text submission | Flag incomplete waypoint path; disable run until origin/dest set |
| **Loading** | Shimmer skeleton matching exact 3-pane geometry (`WorkspaceInitSkeleton`, `CockpitDetailSkeleton`) | 4-card metric skeleton + chart loading shimmer; zero layout displacement | Profile header skeleton + ledger table placeholder rows | Animated pulsating typing indicator (`smart_toy` pulse) | Interactive map placeholder with subtle pulsing center reticle |
| **Empty** | "No cases matching filter" card with clear filters button | "No historical events in selected time window" illustration | "No adjudications committed in this period" ledger empty card | "No active dispute found for this trip" notice | Blank canvas with "Click map to set Origin waypoint" guide |
| **Locked** | Amber lock banner with analyst name & countdown TTL; read-only mode for non-owners | Read-only view for general analysts; edit boundaries for managers | Active lease banner with countdown clock and "Resume Case →" trigger | Input disabled when case already escalated or finalized | Controls locked during active simulation run playback |
| **Error** | Red alert banner with error code, retry button, and auto-escalation trigger | Red inline badge with failed provider notice and last-healthy timestamp | Red toast notification on failed ledger fetch with retry action | Red notification on delivery failure with auto-escalation notice | Red parameter highlight with validation message on invalid input |

---

## 6. API Data Mappings

| UI Component | HTTP Method & Path | Auth & Role Requirements | Request Payload | Response Schema |
|---|---|---|---|---|
| **Triage Queue** | `GET /api/v1/cases` | `analyst`, `senior_analyst`, `manager` | Query: `status`, `search`, `severity`, `limit`, `offset` | `CaseListResponse` |
| **Case Detail** | `GET /api/v1/cases/{case_id}` | `analyst`, `senior_analyst`, `manager` | Path: `case_id` | `CaseDetailResponse` |
| **Claim Case** | `POST /api/v1/cases/{case_id}/claim` | `analyst`, `senior_analyst` | None (Principal derived from token) | `CaseActionResponse` |
| **Adjudicate** | `POST /api/v1/cases/{case_id}/adjudicate` | `analyst`, `senior_analyst` | `AdjudicationRequest` (outcome, rationale, fine_amount) | `AdjudicationResponse` |
| **Analyst Chat** | `POST /api/v1/cases/{case_id}/chat` | `analyst`, `senior_analyst` | `ChatRequest` (message, reset_context) | SSE Event Stream |
| **Analytics** | `GET /api/v1/analytics/metrics` | `analyst`, `senior_analyst`, `manager` | Query: `window_days` (7, 30, 90) | `AnalyticsMetricsResponse` |
| **Analyst Profile** | `GET /api/v1/analyst/audit` | `analyst`, `senior_analyst`, `admin` | Query: `search`, `verdict`, `limit`, `offset` | `AnalystAuditProfileResponse` |
| **Driver Dispute** | `GET /api/v1/driver/cases/{case_id}` | `driver` (must match case driver ID) | Path: `case_id` | `DriverCaseDetailResponse` |
| **Driver Chat** | `POST /api/v1/driver/cases/{case_id}/chat` | `driver` (must match case driver ID) | `DriverChatRequest` (message, action) | SSE Event Stream |

---

## 7. Driver-First Lifecycle Reconciliation (#147 & ADR-018)

Per stakeholder approval by Pham Thanh Dat (@datamonsterr) in [#147](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/147) and [ADR-018](../architecture/adr-018-driver-first-resolution.md):

1. **Intake Sequence:** A detected case enters Driver assistance BEFORE active Analyst triage (`FR-DF-01`).
2. **Confidence Semantics:**
   - Raw classifier confidence is stored in `[0, 1]` with `score_semantics=uncalibrated_model_confidence`.
   - Confidence represents suspected violation probability; it is NOT measured guilt probability or accuracy (`FR-DF-02`).
   - Confidence strictly `> 0.5`: System asks whether Driver still wants to appeal.
   - Missing, invalid, or exactly `0.5` confidence escalates to Analyst triage (`FR-DF-02`).
3. **Driver Confirmed Resolution:**
   - When Driver chooses "No further appeal", the case commits explicit **Driver confirmed resolution** (`driver_confirmed_resolution`).
   - This disposition is distinct from Analyst dismissal (`dismissed`), exoneration, or sanctions.
   - Disclosed missing or conflicting evidence is retained with actor confirmation (`FR-DF-05`).
4. **Escalation Rules:**
   - Choosing "Continue appeal" escalates to the fraud Analyst triage queue (`FR-DF-03`).
   - Silence after successfully delivered confirmation question escalates after 48 hours (`FR-DF-06`).
   - Delivery or model failure before confirmation escalates immediately (`FR-DF-07`).
   - Late confirmation cannot reverse an already escalated case (`FR-DF-08`). Only an authorized Analyst can reopen a case.
5. **Analyst Chatbot Context Reset:**
   - The Copilot chat input includes an explicit, unchecked checkbox: `Reset context` (`FR-WS-01`).
   - When checked, omits prior conversational history from the next model request while retaining case evidence and immutable stored audit logs.
6. **Vehicle Plate Search:**
   - Search matches partial driver name, driver ID, and vehicle registration plate (`biển số xe`). License number refers to vehicle plate, not driver license (`FR-WS-02`).

---

## 8. Stitch MCP Traceability

All UI views maintain direct bidirectional traceability with versioned Stitch design projects:

| Application View | Stitch Project | Screen ID | Title / Status |
|---|---|---|---|
| **Adjudication Cockpit** | `projects/12095025610159108305` | `b6375a5e08984b638f8c5b4de2e37584` | Unified Operational Cockpit (3-Pane Workspace) · Approved |
| **Fleet Analytics** | `projects/12095025610159108305` | `d8041f6616b849b29c334477afb6f708` | General Analytics Dashboard View · Approved |
| **Analyst Profile** | `projects/12095025610159108305` | `769b0a40e27541fb8ac0d0fa500de4b4` | Analyst Profile View · Approved |
| **Tester Studio** | `projects/7541683500450336068` | `4eddfaeaaeb3415ab0caf96f58abdc35` | Tester Trip Simulation Studio Workbench · Approved |
| **GIS Evidence** | `projects/7784297700642891517` | `2c6aa50e1e74419497c2e22a5a9a26f7` | Tactical Telemetry & Timeline Control · Approved |

---

## 9. Non-Fabrication & Ethical Language Standards

1. **No Fabricated Operational Data:**
   - All mockup numbers in screenshots or design specifications (e.g., `32.4s MTTR`, `1,420 human signs`, `98.4% model agreement`) are illustrative design examples only.
   - Runtime production views must render live database aggregates or explicitly state `"N/A"` / `"—"` when metrics are uncalculated or unobserved.
2. **Neutral Forensics Over Guilt Semantics:**
   - Use objective descriptive terminology: `Suspected route deviation`, `Stationary stall duration`, `GPS jitter`, `Uncorroborated anomaly`.
   - Never use premature or accusatory labels like `"Guilty driver"`, `"Fraudster confirmed"`, or `"Definite cheater"` before signed human adjudication.
3. **Role-Based Sanction Restrictions:**
   - Junior analysts (`fraud_analyst`) cannot execute suspensions exceeding 24 hours or fines exceeding 2,000,000 VND without supervisor co-signature (`FR-WS-05`).
   - Exoneration receipts in Driver Care explicitly state the factual basis (e.g. `Traffic gridlock verified via TomTom peer flow`).

---

## 10. Accessibility (a11y) & Keyboard Navigation

1. **Target Viewports:** High-density desktop monitors from 1280x800 to 2560x1440. Layouts do not collapse into single-column mobile views.
2. **Contrast Benchmarks:** All body typography, status badges, and data cells meet WCAG 2.1 AAA contrast ratios (≥ 7:1 for text, ≥ 4.5:1 for graphical elements).
3. **Keyboard Shortcuts:**
   - `J` / `K`: Navigate down / up the priority triage queue.
   - `Ctrl + K` / `Cmd + K`: Open global search (driver name, plate, case ID).
   - `1` / `2` / `3` / `4`: Switch center panel tabs (`Overview`, `Conversation`, `Driver Info`, `Workflow Synthesis`).
   - `Escape`: Close modals, drawer panels, or search overlays.
4. **Screen Reader Compliance:**
   - All icon-only buttons include descriptive `aria-label` and `title` attributes.
   - Dynamic SSE streams announce incoming updates using `aria-live="polite"`.
   - Critical error banners use `role="alert"` and `aria-live="assertive"`.
