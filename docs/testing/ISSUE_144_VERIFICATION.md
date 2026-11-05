# Issue #144 Verification Evidence: Claimed-Case Visibility & Concurrency

## Objective
Verify that claimed cases are synchronized across analyst sessions:
1. When Analyst A claims a case, it is excluded from Analyst B's available queue without manual refresh.
2. Analyst A can resume their claimed case under "My Cases" (`availability=mine`).
3. Stale claim or stale decision attempts return 409 Conflict with clear error feedback.
4. Other analysts see read-only lock notifications and cannot adjudicate rows claimed by peers.
5. Releasing the lease or waiting for 300s inactivity restores the case to available triage queues.

## Verification Evidence

### 1. Backend Concurrency & API Regressions (`pytest tests/test_api/test_queue_lease_sync.py`)
```
tests/test_api/test_queue_lease_sync.py::test_concurrent_analysts_available_queue_filters_foreign_leases PASSED
tests/test_api/test_queue_lease_sync.py::test_stale_claim_conflict_returns_409 PASSED
tests/test_api/test_queue_lease_sync.py::test_stale_adjudication_conflict_returns_409 PASSED
tests/test_api/test_queue_lease_sync.py::test_lease_release_and_expiration_restores_available_queue PASSED
tests/test_api/test_queue_lease_sync.py::test_foreign_analyst_cannot_release_lease PASSED

============================== 5 passed in 0.37s ===============================
```

### 2. Frontend React / Cockpit Vitest Suite (`vitest run tests/queue-lease-sync.test.tsx`)
```
 ✓ tests/queue-lease-sync.test.tsx (4 tests) 853ms
   ✓ Queue Lease Sync & Concurrency UI (Issue #144) (4)
     ✓ renders read-only review lock notice banner and disables claim and decision buttons when case is locked by another analyst
     ✓ recovers from 409 conflict on stale claim attempt by removing stale row and refetching
     ✓ recovers from 409 conflict on stale decision submit by refetching detail and queue
     ✓ runs periodic background queue sync at 10s interval

 Test Files  1 passed (1)
      Tests  4 passed (4)
```

### 3. Full Webapp Suite
```
 Test Files  24 passed (24)
      Tests  147 passed (147)
   Duration  8.01s
```

### 4. Code Quality & Standards
```
/home/dat/dev/vinuni_aia/GreenSentinel/.venv/bin/ruff check src/ tests/
All checks passed!
```
