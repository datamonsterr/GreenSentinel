> Historical POC v2 document. This is not an active Sprint 2 acceptance runbook. Its autonomous-dismissal and driver-expansion scenarios conflict with the current PRD boundary; analyst confirmation remains required. Use the active [manual guide](../manual/README.md) and [contributor rules](../../../CONTRIBUTING.md). Product reconciliation remains tracked separately in #72/#73.

# GreenSentinel - POC v2 Manual Test Runbook (Happy & Error Paths)

**Target Audience:** QA Engineers, Product Managers, Fraud Analysts, Technical Presenters (Demo Day)
**System Architecture:** 3-Tier Layered Architecture (`src/api`, `src/services`, `src/agents`, `src/webapp`)
**Safety Invariants:** Zero Automated Sanctions (NFR-L06-02); Autonomous Exoneration only with deterministic telemetry proof.
**Production URLs:**
- Driver Mobile Portal: `https://green-sentinel-driver.vercel.app/driver`
- Fraud Analyst Cockpit: `https://green-sentinel.vercel.app/workplace`
- Local Backend API: `http://localhost:8000`

---

## 1. Prerequisites & Environment Setup

### 1.1 Backend Service
Start the FastAPI backend service with test/development configuration:

```bash
# In repo root directory
source .venv/bin/activate
export APP_ENV=development
export PORT=8000

uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

Verify backend health:
```bash
curl -s http://localhost:8000/api/v1/health | jq .
# Expected: {"status": "ok", "env": "development", "database": "connected"}
```

### 1.2 Frontend Webapp
Start the Next.js web application:

```bash
cd src/webapp
pnpm install
pnpm dev --port 3000
```

Verify webapp availability:
- **Cockpit Portal:** [http://localhost:3000/workplace](http://localhost:3000/workplace)
- **Mobile Driver Portal Landing:** [http://localhost:3000/driver](http://localhost:3000/driver)
- **Mobile Driver Dispute Page:** `http://localhost:3000/driver/dispute/[caseId]`

---

## 2. Comprehensive Test Matrix

| # | Test Scenario | Classification | Target Case ID | Target Driver ID | Expected Behavior & Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **HP-01** | Autonomous Exoneration | Happy Path | `018f2f4e-a000-7000-8000-000000000026` | `018f2f4e-3000-7000-8000-000000000002` | `auto_dismissed`, Exoneration Receipt issued, 0 penalty |
| **HP-02** | A2A Collaboration & HITL Adjudication | Happy Path | `018f2f4e-a000-7000-8000-000000000001` | `018f2f4e-3000-7000-8000-000000000001` | `in_dispute` -> `evidence_requested` -> `resolved` via Analyst |
| **EP-01** | Expired Dispute Window (> 48h) | Error Path | `test-case-expired-001` | `018f2f4e-3000-7000-8000-000000000001` | `dispute_status: closed`, Red warning banner, Inputs disabled |
| **EP-02** | Past Repeat Offender Sanctions | Error Path | `test-case-sanctions-001` | `drv-repeat-offender` | Exoneration rejected; escalated to Analyst review (`in_dispute`) |
| **EP-03** | Mock GPS / Telemetry Anomaly | Error Path | `test-case-mock-gps-001` | `drv-spoofed-001` | Exoneration rejected; flagged anomalous; escalated (`in_dispute`) |
| **EP-04** | Driver RBAC Identity Mismatch | Error Path | `018f2f4e-a000-7000-8000-000000000026` | `018f2f4e-3000-7000-8000-000000000099` | HTTP 403 Forbidden; UI card "Bạn không có quyền truy cập..." |
| **EP-05** | Non-Existent / Invalid Case ID | Error Path | `non-existent-case-uuid` | Any | HTTP 404 Not Found; UI card "Không tìm thấy hồ sơ vụ việc" |
| **EP-06** | Finalized Case Re-dispute Block | Error Path | `018f2f4e-a000-7000-8000-000000000026` | `018f2f4e-3000-7000-8000-000000000002` | Informative notice "Vụ việc đã xử lý xong"; status locked |
| **EP-07** | Blank / Whitespace Message | Error Path | `018f2f4e-a000-7000-8000-000000000001` | `018f2f4e-3000-7000-8000-000000000001` | HTTP 422 Unprocessable Entity; UI validation warning |
| **EP-08** | SSE Network Disconnect & Retry | Error Path | `018f2f4e-a000-7000-8000-000000000001` | `018f2f4e-3000-7000-8000-000000000001` | Error notification with "Thử kết nối lại" (Retry) action |

---

## 3. HP-01 Walkthrough: Driver Mobile Dispute & Autonomous Exoneration

### Objective
Demonstrate the driver-facing dispute workflow where physical road conditions (heavy congestion, average speed 3.2 km/h, duration ratio 2.7x) deterministically corroborate the driver's explanation, triggering immediate autonomous exoneration without human analyst intervention.

### Step-by-Step Execution

1. **Access Mobile Dispute Interface:**
   - Open browser at `http://localhost:3000/driver/dispute/018f2f4e-a000-7000-8000-000000000026` (simulated mobile view, 375x812px viewport recommended).
   - **UI Verification:**
     - Header displays: `GreenSM Sentinel - Driver Care`.
     - Alert card shows violation code `ERR-01: Tài xế cố tình kéo dài thời gian đón khách (Driver-Induced Delay / Stall)`.
     - Deadline banner shows 48-hour dispute window countdown.
     - Sentinel AI Assistant posts welcome greeting in Vietnamese.
     - 4 Quick Claim Chips are rendered: `🚦 Heavy Traffic / Kẹt xe`, `📍 GPS / App Drop`, `⏱️ Passenger Wait`, `⚠️ Vehicle Breakdown`.

2. **Submit Traffic Gridlock Claim:**
   - Tap on the `🚦 Heavy Traffic / Kẹt xe` quick chip.
   - Text input auto-populates: `"Khu vực bị kẹt xe nghiêm trọng khiến xe không thể di chuyển đúng tiến độ."`
   - Tap **Gửi (Send)** button.

3. **Observe SSE Streaming & Deterministic Corroboration:**
   - Sentinel Agent responds via real-time SSE token stream.
   - The Driver Agent executes the deterministic traffic corroboration rule:
     - Observed Speed: `3.2 km/h < 5.0 km/h` ✅
     - Duration Ratio: `2.7x >= 2.0x` ✅
     - Valid GPS Telemetry: `True` ✅
     - Prior Sanctions: `0` ✅

4. **Verify Autonomous Exoneration Output:**
   - Status badge transitions from `NOT_DISPUTED` to `AUTO_DISMISSED`.
   - Sentinel Agent displays the official exoneration statement:
     > *"Khiếu nại được xác nhận tự động qua dữ liệu viễn thông giao thông thực tế. Đoạn đường ghi nhận ùn ứ nghiêm trọng (vận tốc TB: 3.2 km/h, tỷ lệ thời gian vượt 2.7x). Vụ việc được hủy bỏ tự động (Auto-Dismissed) và không áp dụng bất kỳ chế tài nào."*
   - An emerald **Digital Exoneration Receipt** appears with:
     - `Receipt ID`: UUIDv4
     - `Verdict`: `EXONERATED`
     - `Corroboration Metrics`: Speed 3.2 km/h, Delay Ratio 2.7x, Congestion Heavy
     - `Applied Sanctions`: `NONE (0 VND, No Account Penalty)`

> [!IMPORTANT]
> **Safety Invariant Check (NFR-L06-02):** The driver's account remains active, 0 sanctions applied, and the case terminates without requiring manual analyst approval.

---

## 4. HP-02 Walkthrough: Cockpit A2A Dispute Dossier, Analyst Delegation, and HITL Adjudication

### Objective
Demonstrate multi-agent collaboration (A2A handoff) when a driver's claim cannot be autonomously corroborated, escalating to an analyst with compiled dispute dossier, delegating inquiries to the Driver Agent, and finalizing human adjudication.

### Step-by-Step Execution

#### Phase 1: Driver Dispute Submission & Escalation
1. Open mobile browser at `http://localhost:3000/driver/dispute/018f2f4e-a000-7000-8000-000000000001`.
2. Enter message: `"Đường rất đông đúc vào giờ cao điểm nên tôi bị trễ vài phút"`.
3. Tap **Gửi (Send)**.
4. **Agent Escalation:**
   - Because telemetry shows normal driving speeds (28 km/h), the Driver Agent determines the claim is uncorroborated.
   - Status transitions to `IN_DISPUTE` (`driver_disputed`).
   - Agent informs the driver that the case has been escalated to an independent Fraud Analyst for manual review.

#### Phase 2: Analyst Cockpit Review & Lease Claim
1. Open desktop browser at [http://localhost:3000/workplace](http://localhost:3000/workplace).
2. Ensure you are signed in as an Analyst (`Tuấn LM` or principal ID `018f2f4e-1000-7000-8000-000000000001`).
3. Locate case `#00000001` in the Left Queue panel. Status is `driver_disputed`.
4. Select the case and click the **Claim Case Lock** icon.
   - Lease locks exclusively for 300 seconds.
   - Status changes to `in_review`.

#### Phase 3: Dispute Dossier & Multi-Agent Synthesis
1. In the Center Panel under **Case Evidence**, examine the **Driver Dispute Synthesis** dossier:
   - **Header:** `Driver Dispute Synthesis` with badge `IN_DISPUTE` and `Rec: Review Driver Statement`.
   - **Claim Type:** `traffic_gridlock`.
   - **Verbatim Statement:** `"Đường rất đông đúc vào giờ cao điểm nên tôi bị trễ vài phút"`.
   - **Telemetry Signals:** Speed `28.5 km/h`, Traffic Ratio `1.1x`, Precedent Score `0.88`.
2. Click **Verbatim Transcript (2 turns)**: Expands to show chronological turns between Driver and Sentinel Driver Agent.

#### Phase 4: A2A Inquiry Delegation
1. In the **Delegate question to Driver Agent** box at the bottom of the Dossier:
   - Type instruction: `"Tài xế vui lòng cung cấp địa điểm cụ thể hoặc hình ảnh phương tiện gặp sự cố"`.
   - Click **Delegate**.
   - Observe confirmation toast: `Question delegated to Driver Agent`.
   - Case status shifts to `evidence_requested` (`pending`).
2. Switch to the Driver's mobile window (`/driver/dispute/018f2f4e-a000-7000-8000-000000000001`):
   - A new inquiry appears:
     > *"[Yêu cầu từ Chuyên viên giám sát]: Tài xế vui lòng cung cấp địa điểm cụ thể hoặc hình ảnh phương tiện gặp sự cố"*
3. Driver replies: `"Tôi bị kẹt ở lối rẽ Nguyễn Chí Thanh do có xe buýt chết máy chắn ngang"`.
4. Refresh/poll the Cockpit dossier: Verbatim Transcript updates to 4 turns.

#### Phase 5: Human Adjudication (HITL)
1. In the bottom Decision Action bar of the Cockpit Center Panel:
   - Enter rationale: `"Đã xác minh nguyên nhân kẹt xe đột xuất từ giải trình bổ sung của tài xế. Chấp thuận miễn trừ trách nhiệm."`
   - Click the green **Send / Action Menu** button and select **Approve**.
2. Case transitions to `resolved` terminal state, version increments to `v2`, lease releases, and case clears from the active queue.

---

## 5. Error Path Scenarios & Edge Cases

### 5.1 EP-01: Expired Dispute Window (> 48 hours)
- **Condition:** Case `dispute_deadline` is in the past.
- **Test Steps:**
  1. Open `/driver/dispute/[caseId]` with an expired case deadline.
  2. **UI Verification:**
     - A red warning banner displays: `"Thời hạn gửi khiếu nại (48h) đã kết thúc"`.
     - The chat input textarea is disabled (`disabled={isExpired}`).
     - Quick-claim chips are disabled and unclickable.
     - The Send button is disabled.
  3. **API Verification:**
     ```bash
     curl -s -X POST "http://localhost:8000/api/v1/driver/cases/test-case-expired-001/chat" \
       -H "Content-Type: application/json" \
       -d '{"message": "Tôi muốn giải trình trễ"}' | jq .
     # Expected: {"dispute_status": "closed", "reply": "Thời hạn gửi khiếu nại (48 giờ) đã kết thúc...", "needs_analyst_review": false}
     ```

### 5.2 EP-02: Repeat Offender Past Sanctions Gate (NFR-L06-02)
- **Condition:** Driver has 1 or more past sanctions (`prior_sanctions >= 1`).
- **Test Steps:**
  1. Submit traffic claim for a case assigned to a repeat offender driver.
  2. Telemetry shows low speed (< 5 km/h) and high ratio (> 2.0x).
  3. **Verification:**
     - Autonomous exoneration **MUST NOT** trigger.
     - Status transitions to `in_dispute` (`driver_disputed`).
     - Agent informs driver: *"Hồ sơ ghi nhận lịch sử xử lý trước đây, vụ việc được chuyển tiếp tới Chuyên viên để đánh giá trực tiếp."*
     - No exoneration receipt is generated.

### 5.3 EP-03: Mock GPS & Telemetry Anomaly Gate
- **Condition:** Driver device reports mock location or invalid GPS timestamps (`gps_valid: false`).
- **Test Steps:**
  1. Submit traffic dispute where driver trajectory contains mock location / teleportation markers.
  2. **Verification:**
     - The deterministic safety check flags `gps_valid = false`.
     - Autonomous exoneration is blocked.
     - Dispute dossier flags `telemetry_anomaly: true`.
     - Escalated to Fraud Analyst with high risk score.

### 5.4 EP-04: Driver RBAC Cross-Account Access Block (HTTP 403)
- **Condition:** Driver B attempts to access or dispute Case A belonging to Driver A.
- **Test Steps:**
  1. Call driver dispute endpoint with a mismatched `X-Driver-ID`:
     ```bash
     curl -s -X GET "http://localhost:8000/api/v1/driver/cases/018f2f4e-a000-7000-8000-000000000026/dispute" \
       -H "X-Driver-ID: 018f2f4e-3000-7000-8000-000000000099" \
       -H "X-Role: driver" | jq .
     # Expected: HTTP 403 Forbidden {"detail": "Driver identity does not match current session"}
     ```
  2. **UI Verification:**
     - Opening `/driver/dispute/[caseId]` as an unauthorized driver displays the access denied card:
       `"Bạn không có quyền truy cập hồ sơ vụ việc của đối tác khác"` with button `"Về cổng tài xế"`.

### 5.5 EP-05: Non-Existent / Invalid Case ID (HTTP 404)
- **Condition:** User accesses `/driver/dispute/invalid-uuid`.
- **Test Steps:**
  1. Call dispute endpoint with unknown ID:
     ```bash
     curl -s -X GET "http://localhost:8000/api/v1/driver/cases/non-existent-uuid/dispute" | jq .
     # Expected: HTTP 404 Not Found {"detail": "Case non-existent-uuid not found"}
     ```
  2. **UI Verification:**
     - UI displays friendly card: `"Không tìm thấy hồ sơ vụ việc"` with suggestion to check case ID and button `"Về cổng tài xế"`.

### 5.6 EP-06: Finalized Case Re-dispute Block
- **Condition:** Driver attempts to submit additional chat on a case that is already `auto_dismissed` or `resolved`.
- **Test Steps:**
  1. Driver sends chat on already dismissed case:
     ```bash
     curl -s -X POST "http://localhost:8000/api/v1/driver/cases/018f2f4e-a000-7000-8000-000000000026/chat" \
       -H "Content-Type: application/json" \
       -d '{"message": "Gửi thêm lý do"}' | jq .
     # Expected: {"reply": "Vụ việc đã được xử lý xong (Trạng thái: auto_dismissed). Khiếu nại đã kết thúc.", "is_auto_dismissed": true, "needs_analyst_review": false}
     ```
  2. **UI Verification:**
     - The interface displays the green/gray resolution banner: `"Hồ sơ đã được xử lý hoàn tất"` and preserves the previous exoneration receipt.

### 5.7 EP-07: Blank / Whitespace Message Validation (HTTP 422)
- **Condition:** Submission of empty string or pure whitespace.
- **Test Steps:**
  ```bash
  curl -s -X POST "http://localhost:8000/api/v1/driver/cases/018f2f4e-a000-7000-8000-000000000001/chat" \
    -H "Content-Type: application/json" \
    -d '{"message": "   "}' | jq .
  # Expected: HTTP 422 Unprocessable Entity {"detail": [{"msg": "Dispute message cannot be empty or whitespace"}]}
  ```

### 5.8 EP-08: SSE Stream Interruption & Recovery
- **Condition:** Network connection drops during token streaming.
- **Test Steps:**
  1. In browser DevTools Network tab, set Throttling to Offline mid-stream.
  2. UI catches stream error and displays: `"Lỗi kết nối khi gửi khiếu nại. Vui lòng kiểm tra mạng và thử lại."`
  3. Click `"Thử kết nối lại"` (Retry) button: Automatically resubmits the last pending message and restores streaming.

---

## 6. Mobile Driver Care Portal Walkthrough (`/driver`)

The Driver Care Portal provides an accessible entry point for taxi drivers:
1. Navigate to `https://green-sentinel-driver.vercel.app/driver` (or `http://localhost:3000/driver`).
2. **Branding & Header:**
   - GreenSM badge and emerald theme matching VinFast EV fleet styling.
   - Title: **Cổng Thông Tin Đối Tác GreenSM (Driver Care Portal)**.
3. **Quick Case Access:**
   - Enter a Case ID into the input field.
   - Tap **Mở khiếu nại (Open Dispute)** -> Instantly redirects to `/driver/dispute/[caseId]`.
4. **Interactive Demo Candidates:**
   - **Candidate 1 (Traffic Exoneration):** One-tap shortcut to Case `#00000026` to demo instant autonomous dismissal.
   - **Candidate 2 (Analyst HITL):** One-tap shortcut to Case `#00000001` to demo Cockpit escalation and A2A follow-up.
5. **Driver Rights & Policy Summary:**
   - SLA Guarantee: 48-hour dispute window.
   - Safety Commitment: 0 automatic financial penalties (NFR-L06-02).
   - Real-time 24/7 AI Assistant.

---

## 7. Rollback & State Reset Procedure

To cleanly reset cases and test state between demo sessions:

```bash
# Reset case status via simulation re-trigger:
curl -X POST http://localhost:8000/api/v1/simulations/intentional_dic -H "X-Role: demo_operator"
curl -X POST http://localhost:8000/api/v1/simulations/traffic_gridlock -H "X-Role: demo_operator"

# In PostgreSQL (if using local database directly):
psql -h localhost -p 54322 -U postgres -d postgres -c "
  SET search_path = app, extensions, public;
  UPDATE app.fraud_cases SET status = 'ready', dispute_status = 'not_disputed', version = 1;
  DELETE FROM app.review_leases;
  DELETE FROM app.adjudications;
  DELETE FROM app.case_agent_messages;
"
```

---

## 8. Automated & Live Verification Report (Dev Deployment)

### 8.1 Automated Suite Pass Rates
- **Backend (Pytest):** 317 passed, 3 skipped, 0 failed (100% green).
- **Frontend (Vitest):** 13 test files, 87 passed, 0 failed (100% green).
- **E2E (Playwright):** 6 tests passed, 0 failed (100% green).

### 8.2 Live Cloud Deployment Status
| Service | Environment URL | Status | Verified Functionality |
|---|---|---|---|
| **Analyst Cockpit** | `https://green-sentinel-dev.vercel.app` | ✅ Active | Clerk sign-in gate, triage queue, rich XML widgets, attachment button |
| **Driver Care Portal** | `https://green-sentinel-dev.vercel.app/driver` | ✅ Active | Case lists, active sessions, quick-chips, interactive map trigger |
| **Railway Backend** | `https://greensentinel-backend-dev.up.railway.app` | ✅ Active | Fast redeploy, PostgreSQL connected, 100 cases seeded |

### 8.3 Live `agent-browser` Verification Evidence
1. **Autonomous Exoneration (HP-01):**
   - Verified on Case `#018f2f4e-a000-7000-8000-000000000026`.
   - Captured screenshot: [`docs/testing/screenshots/driver-dispute-exonerated.png`](file:///docs/testing/screenshots/driver-dispute-exonerated.png).
   - Confirms automatic dismissal, 0 VNĐ penalty sanction, receipt generation (`REC-AUTO`), and disabled post-verdict inputs.
2. **Interactive GSupport Chatbot & Policy RAG:**
   - Verified on Case `#018f2f4e-a000-7000-8000-000000000100`.
   - Captured screenshot: [`docs/testing/screenshots/driver-dispute-chat-submitted.png`](file:///docs/testing/screenshots/driver-dispute-chat-submitted.png).
   - Confirms quick-claim chip click (`🚦 Heavy Traffic / Kẹt xe`), instant submission, policy citation card (Điều 12.2 Quy chế GreenSM - 96% match), and live GPS telemetry stats (`4.8 km/h`, `3.4x`).
3. **Cockpit Analyst Agent Tools & Live APIs:**
   - Verified via live SSE stream on `/api/v1/policy/chat/stream`.
   - Live tool `check_weather_condition` verified via Open-Meteo API returning clear sky, 33.3°C, 0.0mm rain, and `<weather_widget>` payload.
