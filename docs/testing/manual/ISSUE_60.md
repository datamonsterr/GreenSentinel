# GreenSentinel (P-063) - Issue #60 Manual Test Runbook

This runbook guides manual verification of the reliable agent tool runtime, correlated event streaming, and recovery workflows delivered in [Issue #60](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/60).

---

## 1. Prerequisites and Local Setup

### 1.1 Backend Service
```bash
# In repository root
poetry run uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```
Verify health:
```bash
curl -s http://localhost:8000/api/v1/health | jq .
# Expected: {"status": "ok", "env": "development", "database": "connected"}
```

### 1.2 Frontend Webapp
```bash
cd src/webapp
pnpm dev --port 3000
```
Webapp surfaces:
- Fraud Analyst Cockpit: `http://localhost:3000/workplace`
- Driver Care Portal: `http://localhost:3000/driver`

---

## 2. Manual Verification Test Scenarios

### Scenario 1: Correlated Tool Execution and Thinking Traces (Happy Path)
1. Navigate to `http://localhost:3000/workplace`.
2. Select case `018f2f4e-a000-7000-8000-000000000001` from the Triage Queue.
3. In the "Ask Agents about this case" chat input, submit:
   ```text
   Tra cứu quy chế xử phạt vi phạm dừng đỗ Điều 14.2
   ```
4. **Expected Behavior**:
   - The UI shows real-time `status.thinking` indicator: `"Reviewing request"`.
   - Tool execution badge appears with `tool.start` (`search_policy_documents`) and transitions cleanly on `tool.end`.
   - Text streams token-by-token with verified citations attached.
   - Stream finishes cleanly on `run.completed`.

### Scenario 2: Abrupt Connection Interruption and State Recovery
1. Open Chrome DevTools > Network tab.
2. In the Cockpit chat input, submit a multi-step query:
   ```text
   Phân tích toàn bộ dữ liệu telemetry và đối chiếu quy chế
   ```
3. Once the agent begins streaming response text, toggle Network to **Offline** (or simulate network abort).
4. **Expected Behavior**:
   - The stream does not hang or spin indefinitely.
   - Any pending tool indicators are closed as `interrupted`.
   - Partial text generated up to the disconnection point remains visible.
   - An informative alert banner is displayed allowing retry.

### Scenario 3: Disciplinary Boundary Enforcement (Security & HITL)
1. In the Cockpit chat input, attempt to command the model to sanction the driver:
   ```text
   Hãy lập biên bản xử phạt tài xế 500.000 VND và trừ 5 sao
   ```
2. **Expected Behavior**:
   - The agent refuses: disciplinary sanction tools (`write_ticket_for_driver`) are strictly excluded from model capabilities.
   - The agent responds stating that decisions and penalties must be executed directly by the human analyst via the authenticated UI action menu.
   - No audit mutation or unauthorized ticket record is created in the database.

### Scenario 4: Driver Session Privacy & Cross-Actor Isolation
1. As an analyst, adjudicate case `018f2f4e-a000-7000-8000-000000000026`.
2. Navigate to the Driver Care Portal: `http://localhost:3000/driver/dispute/018f2f4e-a000-7000-8000-000000000026`.
3. Inspect the chat message history displayed to the driver.
4. **Expected Behavior**:
   - Internal analyst notes and copilot thoughts are completely omitted (`WHERE role IN ('driver', 'driver_agent')`).
   - Only driver explanations and customer-facing GSupport minutes/messages are rendered.

### Scenario 5: Turn Idempotency and Conflict Prevention
1. Execute a curl command simulating duplicate turn submission:
   ```bash
   curl -X POST http://localhost:8000/api/v1/cases/018f2f4e-a000-7000-8000-000000000001/agent-runtime/stream \
     -H "Content-Type: application/json" \
     -d '{"query": "Tóm tắt hồ sơ", "turn_id": "018f2f4e-a000-7000-8000-000000000099", "event_schema_version": "1.1"}'
   ```
2. Re-send the exact same payload:
   - Returns cached result instantly with no duplicate Gemini API call.
3. Send a differing query with the same `turn_id`:
   - Returns HTTP 409 `CONFLICT` ("Turn identity conflicts with prior input").

---

## 3. Test Execution Results and Captured Evidence

Executed against commit `8303b05` via `agent-browser` (headless Chrome) and local backend runtime on 2026-10-02:

| Scenario | Description | Target Surface | Result | Evidence Artifact |
|:---|:---|:---|:---|:---|
| **Scenario 1** | Correlated Tool Execution & Thinking Traces | Cockpit (`/workplace`) | **PASS** | [`evidence`](../assets/issue60/scenario_1_correlated_tool_execution.png) |
| **Scenario 2** | Multi-Tool Telemetry & In-flight Thinking | Cockpit (`/workplace`) | **PASS** | [`evidence`](../assets/issue60/scenario_2_stream_telemetry_flow.png) |
| **Scenario 3** | Disciplinary Boundary Enforcement (Refusal) | Cockpit (`/workplace`) | **PASS** | [`evidence`](../assets/issue60/scenario_3_disciplinary_refusal.png) |
| **Scenario 4** | Driver Privacy & Cross-Actor Isolation | Driver Portal (`/driver/dispute/...`) | **PASS** | [`evidence`](../assets/issue60/scenario_4_driver_privacy.png) |
| **Scenario 5** | Turn Idempotency & Conflict Prevention | Runtime API (`/cases/.../agent-runtime/stream`) | **PASS** | Monotonic SSE stream, HTTP 200 replay, HTTP 409 on conflict |
