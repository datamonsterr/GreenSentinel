# Manual Runbook: Classifier Load & Latency Test

**Document:** `docs/testing/manual/CLASSIFIER_LOAD_TEST.md`  
**Purpose:** Verify latency, throughput, Server-Timing, and inference-time non-functional targets for the R3D fraud classifier service ([PROD_DESIGN.md](../../../research_v2/briefs/PROD_DESIGN.md) §8).

---

## 1. Non-Functional Targets & Acceptance Criteria

Per [PROD_DESIGN.md](../../../research_v2/briefs/PROD_DESIGN.md) §6 and §8, the classifier service must achieve the following acceptance gates on deployed environments:

| Target Metric | Acceptance Threshold | Measurement Source |
|---|---|---|
| **Classifier Inference Latency** | `p95 <= 50 ms` | `Server-Timing: infer;dur=...` or `inference_ms` |
| **API End-to-End Latency** | `p95 <= 300 ms` | Client round-trip time at **concurrency 8** |
| **Error Rate** | `0.0%` (Zero HTTP 5xx / 4xx) | HTTP response status codes |
| **Prediction Accuracy Parity** | Served macro-F1 matches offline R3D (`0.8688`) | Macro-F1 over `dev300` served predictions |
| **Cold Start** | Single-trip initial inference `<= 10 s` | First request immediately following `GET /info` |

---

## 2. Prerequisites

1. **Python Environment:**
   Run using `.venv/bin/python`:
   ```bash
   .venv/bin/python --version  # Python 3.11+
   ```
2. **Benchmark Corpus (`dev300.jsonl`):**
   The load-test CLI defaults to downloading and caching `releases_v2.1/dev300.jsonl` from Hugging Face (`datamonsterr/green-sentinel-synthesized-trips`) with SHA256 verification (`cd008ee10b22520fbd71598d1718d06cf9ba9a9f3af38ca8736a11019a9a9ed9`).
   If offline, specify `--trips <path-to-jsonl>`.
3. **Authentication:**
   Protected endpoints require analyst credentials (`Authorization: Bearer <token>`). Never pass secrets via CLI arguments that could be exposed in `ps` or shell history. Use environment variables.

---

## 3. How to Obtain Preview URLs & Auth Tokens

### 3.1 Resolving the Railway Backend Preview URL
- On Pull Requests, the Railway bot comments the scoped backend preview URL:
  `https://greensentinel-backend-pr-<N>.up.railway.app`
- Alternatively, retrieve it via Railway CLI:
  ```bash
  railway environment
  railway status
  ```

### 3.2 Obtaining a Clerk Session Bearer Token
Hosted environments enforce Clerk session validation ([src/api/auth.py](../../../src/api/auth.py)):
1. **Via Browser Session (Easiest):**
   - Log into the corresponding Vercel preview frontend (`https://<pr-preview>.vercel.app`) using the authorized analyst account (`analyst@greensm.com`).
   - Open Developer Tools (`F12`) -> **Network** or **Application** tab -> **Cookies** / `__session` or copy the `Authorization: Bearer <token>` header from any API request (`/api/v1/cases`, `/api/v1/me`).
2. **Via Environment Variable:**
   Export the token into your shell (the CLI automatically redacts it in reports and console logs):
   ```bash
   export AUTH_TOKEN="eyJhbGciOiJSUzI1NiIs..."
   ```

Supported token environment variables (checked in order):
- `CLASSIFIER_LOAD_TEST_TOKEN`
- `AUTH_TOKEN`
- `CLERK_SESSION_TOKEN`
- `E2E_ANALYST_TOKEN`
- `BEARER_TOKEN`

---

## 4. Execution Commands

### 4.1 Local Development (Uvicorn / Docker)
Start the local FastAPI server with test auth or local credentials:
```bash
# In terminal 1:
export APP_ENV=test
export TEST_AUTH_ENABLED=true
.venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000

# In terminal 2:
export X_ROLE=analyst
.venv/bin/python scripts/loadtest/classifier_load_test.py \
  --base-url http://localhost:8000 \
  --concurrency 1,4,8,16 \
  --requests 100 \
  --warmup 10 \
  --out /tmp/loadtest_local.json \
  --report /tmp/loadtest_local.md
```

### 4.2 Hosted Railway PR Preview
Run the full 300-request suite against the deployed Railway PR environment:
```bash
export AUTH_TOKEN="<analyst-clerk-jwt>"

.venv/bin/python scripts/loadtest/classifier_load_test.py \
  --base-url https://greensentinel-backend-pr-566.up.railway.app \
  --concurrency 1,4,8,16 \
  --requests 300 \
  --warmup 20 \
  --out docs/testing/artifacts/loadtest_preview_pr566.json \
  --report docs/testing/artifacts/loadtest_preview_pr566.md
```

### 4.3 Batch Mode Evaluation (/assess/batch)
Test batch throughput with batch size 8 (up to 64 items per request):
```bash
export AUTH_TOKEN="<analyst-clerk-jwt>"

.venv/bin/python scripts/loadtest/classifier_load_test.py \
  --base-url https://greensentinel-backend-pr-566.up.railway.app \
  --batch-size 8 \
  --concurrency 1,4,8 \
  --requests 100 \
  --report docs/testing/artifacts/loadtest_batch8.md
```

### 4.4 Measuring Advisory Layer Separately
When testing the optional Mercury advisory LLM layer:
```bash
export AUTH_TOKEN="<analyst-clerk-jwt>"

.venv/bin/python scripts/loadtest/classifier_load_test.py \
  --base-url https://greensentinel-backend-pr-566.up.railway.app \
  --advisory \
  --concurrency 1,4 \
  --requests 50 \
  --report docs/testing/artifacts/loadtest_advisory.md
```

---

## 5. How to Read the Generated Report

The CLI emits a Markdown report and structured JSON summary:

```markdown
# Classifier Load Test Report

**Status:** `PASS`
- **Base URL:** `https://greensentinel-backend-pr-566.up.railway.app`
- **Endpoint:** `/api/v1/classifier/assess`
- **Batch Size:** `1`
- **Advisory Enabled:** `False`
- **Auth Token Configured:** `Yes`

## Baseline Measurements
- **Health baseline (GET /health):** 42.1 ms
- **Cold-start client latency:** 188.4 ms
- **Cold-start inference time:** 34.2 ms
- **Cold-start feature time:** 12.1 ms
- **Cold-start HTTP status:** 200

## Concurrency Levels Summary

| Concurrency | Requests | Req/s | Client p50 (ms) | Client p90 (ms) | Client p95 (ms) | Client p99 (ms) | Client Max (ms) | Infer p95 (ms) | Feat p95 (ms) | Errors |
|---|---|---|---|---|---|---|---|---|---|---|
| Concurrency 1 | 300 | 18.2 | 52.1 | 68.4 | 74.2 | 92.0 | 115.4 | 33.1 | 11.2 | 0 (0.0%) |
| Concurrency 4 | 300 | 54.6 | 70.2 | 96.1 | 112.5 | 148.0 | 172.3 | 34.5 | 12.0 | 0 (0.0%) |
| Concurrency 8 | 300 | 82.4 | 94.3 | 145.2 | 178.6 | 240.1 | 290.0 | 36.2 | 12.8 | 0 (0.0%) |
| Concurrency 16 | 300 | 95.1 | 162.0 | 258.4 | 310.2 | 390.5 | 450.2 | 38.0 | 13.5 | 0 (0.0%) |

## Accuracy Sanity Check
- **Served Macro-F1:** `0.8688`
- **Expected Offline R3D Baseline:** `0.8688`
- **Parity Status:** `MATCH`

## Acceptance Criteria (§8 PROD_DESIGN.md)
- **Classifier inference p95 <= 50 ms:** `PASS`
- **Single-trip API p95 <= 300 ms at Concurrency 8:** `PASS`
- **Zero error rate (status 200 OK):** `PASS`
- **Overall Acceptance:** `PASS`
```

### Key Diagnostic Indicators:
1. **Network vs Server Latency:**
   Compare `Health baseline` (pure network transit + ASGI overhead) with `Client p50` and `Infer p95 + Feat p95`.
   If `Client p95` increases while `Infer p95` remains flat, queuing/event-loop saturation is occurring at high concurrency.
2. **Server-Timing Header:**
   The `Server-Timing` header reveals in-process breakdown:
   - `feat;dur=...`: Feature extraction time (R3C tabular features + sequence channel formatting).
   - `infer;dur=...`: In-process inference execution (LightGBM booster + ONNX runtime stacker).
   - `total;dur=...`: Full backend route execution time.
3. **Macro-F1 Accuracy Parity:**
   When evaluated against `dev300.jsonl`, served predictions must equal the expected offline benchmark score `0.8688`. Any drop indicates feature skew or missing model artifacts in production.
