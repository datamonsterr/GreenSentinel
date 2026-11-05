# Manual Test Runbook: Tester Trip Simulation & Workplace Triage

## 1. Overview & Objective
This runbook guides end-to-end manual verification of the **Tester Trip Simulation Cockpit** (`/test`) and **Sandbox Test Workplace** (`/test/workplace`), implementing SPEC-0130 §6.7.

The goal is to verify that:
1. Simulating trip telemetry and GPS anomalies in `/test` triggers real backend APIs and kinematics calculation.
2. The simulation engine automatically registers a synthetic adjudication case (`case-sim-...`) in the isolated test tenancy store.
3. The mock dialogue messages and alerts are intercepted and logged to the sandbox notification sink.
4. Opening `/test/workplace` displays the real data generated from `/test`—including breadcrumbs, DAVI telemetry charts, and intercepted notifications.
5. Adjudication decisions ("Approve", "Sanction", "Investigate") committed in `/test/workplace` update the case status and log immutable audit events to `test_events`.

---

## 2. Prerequisites & Environment Setup

### 2.1 Backend Startup
Ensure the virtual environment is activated and start the FastAPI backend on port `8001` (or `8000`):
```bash
# In repository root
source .venv/bin/activate
export APP_ENV=test
python -m uvicorn src.main:app --host 127.0.0.1 --port 8001 --reload
```

Verify backend health:
```bash
curl -s http://127.0.0.1:8001/api/v1/health | jq .
```

### 2.2 Frontend Startup
Start the Next.js frontend pointing to the backend:
```bash
cd src/webapp
export API_BASE_URL="http://127.0.0.1:8001"
export NEXT_PUBLIC_E2E_TEST="true"  # Bypasses external Clerk auth for sandbox testing
npm run dev -- -p 3000
```

Open your browser to:
- **Cockpit**: `http://localhost:3000/test`
- **Test Workplace**: `http://localhost:3000/test/workplace`

---

## 3. End-to-End Test Procedure

### Scenario A: Trip Simulation Execution in `/test` Cockpit

1. **Navigate to Cockpit**:
   - Open `http://localhost:3000/test`
   - Verify the permanent 3-column spatial layout:
     - **Left Column**: Actor Telemetry Stack (Driver Actor upper-left, Passenger Actor lower-left).
     - **Center Column**: MapLibre vector map viewport with origin, pickup, and destination markers.
     - **Right Column**: Scenario configuration inputs (lat/lon coordinates, speed, driver ID, and fault buttons).

2. **Configure Scenario**:
   - **Origin**: `21.0285`, `105.8524` (Hanoi CBD)
   - **Pickup**: `21.0278`, `105.8520`
   - **Destination**: `21.0480`, `105.8340` (West Lake)
   - **Driver ID**: `drv-sim-001`
   - **Speed**: `15` m/s
   - **Fault Type**: Click **`JUMP`** button (orange highlight). Set offset: `10`s, displacement: `250`m.

3. **Start Simulation**:
   - Click **`Start Simulation`** button in the bottom right panel.
   - **Expected Result**:
     - Button updates to show active run.
     - Simulation status transitions: `QUEUED` → `RUNNING`.
     - Left column displays live updating kinematics: Speed (~15 m/s), Heading, DAVI score, and Step counter (`Step: N/Total`).
     - Center MapLibre map renders moving vehicle marker and blue telemetry breadcrumb trail.
     - When step reaches the fault offset, the vehicle marker jumps by 250m, DAVI score increases (>0.5, colored red), and breadcrumb shows the anomaly jump point.
     - When simulation finishes, status displays `COMPLETED`.

---

### Scenario B: Adjudication & Evidence Review in `/test/workplace`

1. **Switch to Test Workplace**:
   - In the top navigation bar of `/test`, click **`Test Workplace`** (or open `http://localhost:3000/test/workplace`).

2. **Verify Queue Item Auto-Generation**:
   - In the left panel triage queue, look for the newly generated case:
     - ID format: `case-sim-[run_id_prefix]` (e.g., `case-sim-a1b2c3d4`).
     - Risk Score badge: `Risk: 0.92` (high risk due to injected fault).
     - Anomaly tag: `JUMP` (amber chip).
     - Status: `OPEN` (rose badge).

3. **Select Case & Inspect Evidence**:
   - Click the case in the triage queue.
   - **Expected Result**:
     - **Top Right (Telemetry & Map)**:
       - Displays MapLibre vector map with the exact breadcrumb trajectory simulated in `/test`.
       - Click **`Chart`** toggle in the top-right corner: displays dual-axis telemetry chart with speed (blue) and DAVI score (orange) plotted across steps.
       - Click **`Map`** toggle to return to map view.
     - **Bottom Right (Evidence & Intercepted Notifications)**:
       - Evidence card displays `Intercepted Sandbox Notifications (3)`.
       - Dialogue entries appear with channel `APP_INBOX`:
         - `Navigating to pickup.` (To: drv-sim-001)
         - `I'm at the pickup point.` (To: passenger-001)
         - `Passenger boarded. Heading to destination.` (To: drv-sim-001)

4. **Submit Adjudication Decision**:
   - Locate the **Adjudication Rationale & Notes** input field at the bottom.
   - Type rationale: `GPS jump anomaly confirmed by breadcrumb discontinuity and DAVI spike.`
   - Click **`Approve`** (or **`Sanction`**).
   - **Expected Result**:
     - The case status in the queue updates immediately from `OPEN` to `CLOSED`.
     - In the database/repository, an audit event with type `case.triage` is saved in `test_events`.

---

## 4. Direct API Contract Verification (cURL)

You can verify the backend endpoints independently using `curl` with the required `X-Test-Context: true` header:

### 4.1 Boundary Security Enforcement
```bash
# Request without X-Test-Context MUST fail with 400 Bad Request
curl -s -X POST http://127.0.0.1:8001/test/api/v1/plans \
  -H "Content-Type: application/json" \
  -d '{"name": "Unauthorized Plan"}' | jq .
# Expected: {"detail": "Missing or invalid X-Test-Context: true header"}
```

### 4.2 Query Simulation Cases
```bash
curl -s http://127.0.0.1:8001/test/api/v1/cases \
  -H "X-Test-Context: true" | jq .
```

### 4.3 Query Intercepted Notifications for a Run
```bash
curl -s http://127.0.0.1:8001/test/api/v1/runs/<RUN_ID>/notifications \
  -H "X-Test-Context: true" | jq .
```

### 4.4 Submit Case Triage
```bash
curl -s -X POST http://127.0.0.1:8001/test/api/v1/cases/<CASE_ID>/triage \
  -H "Content-Type: application/json" \
  -H "X-Test-Context: true" \
  -d '{
    "decision": "APPROVE_LEGITIMATE",
    "rationale": "Verified through manual runbook test."
  }' | jq .
```

---

## 5. Verification Checklist

| Checkpoint | Pass Criteria | Status |
| :--- | :--- | :---: |
| **Fail-Closed Boundary** | Requests without `X-Test-Context: true` are rejected with HTTP 400 | [ ] |
| **Cockpit 3-Zone UI** | Left Actor stack, Center MapLibre map, Right Scenario inputs are visible simultaneously | [ ] |
| **Live Telemetry SSE** | `/runs/{id}/stream` streams real-time step progress, vehicle coordinates, and DAVI score | [ ] |
| **Fault Vector Injection** | `JUMP`, `DROPOUT`, and `OFFSET_NOISE` apply kinematics changes accurately during execution | [ ] |
| **Case Auto-Generation** | Starting a simulation automatically creates `case-sim-...` with proper risk score in test tenancy | [ ] |
| **Dialogue Interception** | Pre-configured driver/passenger messages are recorded in sandbox notification sink | [ ] |
| **Workplace Map & Chart** | `/test/workplace` renders breadcrumbs on MapLibre and step-by-step curve on Recharts | [ ] |
| **Adjudication Commit** | Triage action transitions case to `CLOSED` and writes immutable audit record to `test_events` | [ ] |
