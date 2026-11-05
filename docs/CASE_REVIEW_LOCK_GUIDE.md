# Case Review Lock & RBAC Manual Testing Guide

This document describes the architectural update mechanism for case claim/release concurrency control, Redis distributed review locking, and role-based access control (RBAC), along with complete step-by-step instructions for manual testing.

---

## 1. Architectural Update Mechanism

### 1.1 Objective & Problems Solved
- **Race Condition Prevention**: Prevents two analysts from reviewing or adjudicating the same case simultaneously.
- **Distributed Concurrency**: Utilizes Redis atomic distributed locks (`SET key val NX EX ttl`) backed by PostgreSQL row locks (`SELECT ... FOR UPDATE`).
- **Role Enforcement (RBAC)**: Restricts claim and release actions to authorized roles (`analyst`, `senior_analyst`, `admin`). Non-analysts are rejected.
- **Admin Preemption**: Allows privileged administrators to break stale locks using `force: true`.
- **Mock ID Interoperability**: Transparently resolves UI mock handles (`case-8921`, `#FC-8921`, `1`) to valid database seed UUIDs while preserving caller-facing aliases.

### 1.2 Lock Architecture & Lifecycle

```
[ Analyst A (Claim) ] ──> [ Check Role (200) ] ──> [ Redis SET NX ] ──> [ DB Lease Record ] ──> Locked (200 OK)
                                                          │
[ Analyst B (Claim) ] ──> [ Check Role (200) ] ──> [ Key Exists!   ] ──────────────────────────> Conflict (409)
                                                          │
[ Driver X  (Claim) ] ──> [ Check Role (403) ] ───────────────────────────────────────────────> Forbidden (403)
                                                          │
[ Admin     (Force) ] ──> [ Role=Admin (200) ] ──> [ Overwrite Lock] ─────────────────────────> Success (200 OK)
                                                          │
[ Adjudication/Final] ──> [ Validate Owner   ] ──> [ Delete Redis  ] ──> [ Delete DB Lease  ] ──> Status: Closed
```

---

## 2. API Specifications

### 2.1 Claim Case Lease
- **Endpoint**: `POST /api/v1/cases/{case_id}/claim`
- **Request Body**:
  ```json
  {
    "analyst_id": "018f2f4e-1000-7000-8000-000000000001",
    "role": "analyst",
    "lease_duration_seconds": 300,
    "force": false
  }
  ```
- **Responses**:
  - `200 OK`: Lease acquired or renewed. Returns lease details (`case_id`, `analyst_id`, `lease_expires_at`, `status`).
  - `403 Forbidden`: Principal does not possess an authorized review role.
  - `409 Conflict`: Case is actively held by another analyst. Response body:
    ```json
    {
      "detail": "Case case-8921 is actively claimed by analyst Tuấn LM until 2026-09-23T08:45:00Z"
    }
    ```

### 2.2 Release Case Lease
- **Endpoint**: `POST /api/v1/cases/{case_id}/release`
- **Request Body**:
  ```json
  {
    "analyst_id": "018f2f4e-1000-7000-8000-000000000001",
    "role": "analyst",
    "force": false
  }
  ```
- **Responses**:
  - `200 OK`: Lease released. Returns `{ "case_id": "...", "status": "released", "released_by": "..." }`.
  - `403 Forbidden`: Caller is not authorized or attempts to release another analyst's lease without admin privileges.

### 2.3 Submit Adjudication Decision (Ownership & Role Enforcement)
- **Endpoint**: `POST /api/v1/cases/{case_id}/adjudicate`
- **Request Body**:
  ```json
  {
    "decision": "actionable",
    "rationale": "GPS teleportation detected",
    "action_type": "deduct_fare",
    "analyst_id": "018f2f4e-1000-7000-8000-000000000001",
    "role": "analyst"
  }
  ```
- **Responses**:
  - `200 OK`: Decision recorded. Automatically deletes temporary Redis lock and marks case terminal status.
  - `409 Conflict`: Case is assigned to or claimed by another analyst.
    ```json
    {
      "detail": "Case case-8921 is assigned to analyst Tuấn LM. Analyst Lê Hoàng Nam is not authorized to submit decisions for this case."
    }
    ```
  - `Admin Override`: A caller with `"role": "admin"` can adjudicate regardless of assignment.

---

## 3. Manual Testing Instructions

### Option A: Manual Testing via cURL (Fastest & Deterministic)

Ensure the backend server is running:
```bash
.venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000
```

#### Step 1: Clean Slate (Force Release)
Release any pre-existing lock as Admin:
```bash
curl -s -X POST http://localhost:8000/api/v1/cases/case-8921/release \
  -H "Content-Type: application/json" \
  -d '{"analyst_id": "admin-01", "role": "admin", "force": true}' | jq .
```
*Expected Output*:
```json
{
  "case_id": "case-8921",
  "status": "released",
  "released_by": "admin-01",
  "released_at": "..."
}
```

#### Step 2: Test Unauthorized Role Rejection (403)
Attempt to claim as a non-analyst (`driver`):
```bash
curl -s -i -X POST http://localhost:8000/api/v1/cases/case-8921/claim \
  -H "Content-Type: application/json" \
  -d '{"analyst_id": "driver-999", "role": "driver", "lease_duration_seconds": 300}'
```
*Expected Output*:
`HTTP/1.1 403 Forbidden` with detail `"Role driver is not authorized to claim case leases."`

#### Step 3: Analyst A Claims Case (200)
Claim case as Analyst A (`Tuấn LM`):
```bash
curl -s -i -X POST http://localhost:8000/api/v1/cases/case-8921/claim \
  -H "Content-Type: application/json" \
  -d '{"analyst_id": "Tuấn LM", "role": "analyst", "lease_duration_seconds": 300}'
```
*Expected Output*:
`HTTP/1.1 200 OK` with JSON body:
```json
{
  "case_id": "case-8921",
  "analyst_id": "Tuấn LM",
  "lease_expires_at": "...",
  "status": "claimed"
}
```

#### Step 4: Verify Concurrency Conflict — Analyst B Blocked (409)
Attempt to claim the same case as Analyst B (`Hoàng Nam`):
```bash
curl -s -i -X POST http://localhost:8000/api/v1/cases/case-8921/claim \
  -H "Content-Type: application/json" \
  -d '{"analyst_id": "Hoàng Nam", "role": "analyst", "lease_duration_seconds": 300}'
```
*Expected Output*:
`HTTP/1.1 409 Conflict` with detail message showing Tuấn LM holds the lease.

#### Step 5: Unauthorized Release Rejection (403)
Analyst B tries to release Analyst A's lock:
```bash
curl -s -i -X POST http://localhost:8000/api/v1/cases/case-8921/release \
  -H "Content-Type: application/json" \
  -d '{"analyst_id": "Hoàng Nam", "role": "analyst", "force": false}'
```
*Expected Output*:
`HTTP/1.1 403 Forbidden` with detail `"Lease is held by another analyst (Tuấn LM). Only the owner or an admin can release it."`

#### Step 6: Authorized Release by Analyst A (200)
Analyst A releases their own lock:
```bash
curl -s -i -X POST http://localhost:8000/api/v1/cases/case-8921/release \
  -H "Content-Type: application/json" \
  -d '{"analyst_id": "Tuấn LM", "role": "analyst", "force": false}'
```
*Expected Output*:
`HTTP/1.1 200 OK` with status `"released"`.

#### Step 7: Analyst B Now Claims (200)
Now that the case is free, Analyst B can claim:
```bash
curl -s -i -X POST http://localhost:8000/api/v1/cases/case-8921/claim \
  -H "Content-Type: application/json" \
  -d '{"analyst_id": "Hoàng Nam", "role": "analyst", "lease_duration_seconds": 300}'
```
*Expected Output*:
`HTTP/1.1 200 OK`.

#### Step 9: Adjudication Decision Ownership Enforcement (409 Blocked)
Analyst B (`Lê Hoàng Nam`) attempts to submit an adjudication decision for a case assigned to or claimed by Analyst A (`Tuấn LM`):
```bash
curl -s -i -X POST http://localhost:8000/api/v1/cases/case-8921/adjudicate \
  -H "Content-Type: application/json" \
  -d '{"decision": "actionable", "rationale": "Testing ownership", "action_type": "deduct_fare", "analyst_id": "Lê Hoàng Nam", "role": "analyst"}'
```
*Expected Output*:
`HTTP/1.1 409 Conflict` with JSON detail stating that Analyst B is not authorized to submit decisions for this case.

#### Step 10: Admin Override Adjudication (200 OK)
Admin submits adjudication decision overriding assignment:
```bash
curl -s -i -X POST http://localhost:8000/api/v1/cases/case-8921/adjudicate \
  -H "Content-Type: application/json" \
  -d '{"decision": "actionable", "rationale": "Admin override", "action_type": "deduct_fare", "analyst_id": "admin-01", "role": "admin"}'
```
*Expected Output*:
`HTTP/1.1 200 OK`. Lock is automatically cleared and case status transitions to `resolved`.

---

### Option B: Manual Testing via Frontend Webapp UI

1. **Start Development Servers**:
   ```bash
   # Terminal 1: Backend
   .venv/bin/uvicorn src.main:app --reload --port 8000

   # Terminal 2: Webapp
   cd src/webapp && npx pnpm dev
   ```
2. **Open Cockpit**:
   - Navigate to `http://localhost:3000` (or configured port) and open the **Cockpit** view (`/workplace`).
3. **Analyst Switcher Toolbar**:
   - In the top action bar, find the Analyst Switcher dropdown:
     - `Tuấn LM (Analyst)`
     - `Lê Hoàng Nam (Analyst)`
     - `Admin Lead (admin)`
4. **Test Claim & Optimistic Updates**:
   - Select **Tuấn LM (Analyst)**. Click **"Nhận hồ sơ"** (Claim Case).
   - Notice the badge immediately changes to `lock Tuấn LM` without lag.
5. **Test Ownership & Decision Submission Guard**:
   - Switch dropdown to **Lê Hoàng Nam (Analyst)**.
   - Observe the **"Gửi phán quyết"** (Submit Decision) button in the right action panel is **disabled** with an explanatory tooltip:
     *"Chỉ chuyên viên đang thụ lý hoặc Admin mới có quyền gửi phán quyết"*.
   - Attempting to claim the case displays a 409 Conflict toast indicating Tuấn LM holds the case.
6. **Test Admin Force Unlock & Override**:
   - Switch dropdown to **Admin Lead (admin)**.
   - The **"Mở khóa"** (Force Release) button is enabled.
   - The **"Gửi phán quyết"** button is **enabled** for Admin, allowing managerial override.

---

### Option C: Inspecting Distributed Locks in Redis

If Redis is running locally (`redis://localhost:6379`):
```bash
# View active review lock key
redis-cli KEYS "review_lock:*"

# Check TTL (time remaining in seconds)
redis-cli TTL "review_lock:018f2f4e-a000-7000-8000-000000000001"

# Check lock payload
redis-cli GET "review_lock:018f2f4e-a000-7000-8000-000000000001"
```

---

## 4. Automated Verification Commands

Run backend automated tests:
```bash
.venv/bin/pytest tests/test_api/test_poc_api.py -k "test_adjudication_blocked_for_unassigned_analyst or test_claim_release_mock_case_redis_lock_and_roles"
```

Run full frontend suite:
```bash
cd src/webapp && npx pnpm test
```
