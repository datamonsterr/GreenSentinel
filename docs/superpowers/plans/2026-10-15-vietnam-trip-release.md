# Synthesized Vietnam Trip Benchmark Release & Preset Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconcile existing 40k preset metadata against Hugging Face pinned release, perform deep EDA on the full 40k corpus, synthesize a deterministic 1,000-trip Vietnam benchmark dataset (`synthesized_vietnam_trip`) with exact class and severity distributions, integrate the Vietnam preset into the tester console with active organization ownership, evaluate strict and enum-blind frozen benchmarks, stage the immutable release, and document findings.

**Tech Stack:** Python 3.13, Pydantic V2, FastAPI, Hugging Face Hub CLI / `huggingface_hub`, Pytest, Ruff.

---

## Background & Discoveries

1. **Preset Metadata Inconsistency:**
   - In `src/services/test_presets.py`, `PUBLISHED_CLASS_COUNTS` previously claimed `ERR-01: 2500, ERR-02: 4000, ERR-03: 2500, ERR-04: 1500, ERR-05: 1500, insufficient_evidence: 3000, no_violation: 28000`, summing to 43,000 trips (> 40,000).
   - The actual pinned Hugging Face manifest at revision `914a36560727f5892a24fba3a4173cb245c963da` records:
     - `no_violation`: 28,000
     - `ERR-01`: 2,000
     - `ERR-02`: 3,200
     - `ERR-03`: 2,000
     - `ERR-04`: 1,200
     - `ERR-05`: 1,200
     - `insufficient_evidence`: 2,400
     - Total: exactly 40,000 trips.
   - This metadata must be corrected truthfully.

2. **Full 40k Geography & Distribution:**
   - The user noted an assumption of US majority. We must measure the actual geography distribution across all 40,000 trips (Porto, NYC, etc.) and report true empirical proportions rather than repeat assumptions.
   - We must compare nested corpus fields (`telemetry`, `assignment`, `driver_profile`, `customer_dispute`, etc.) against `db/migrations` and `docs/architecture/schemas/telemetry-event.schema.json`.

3. **Vietnam Dataset Requirements:**
   - Size: 1,000 distinct trips.
   - Class / Severity Mix:
     - 700 `no_violation`
     - 300 violations: 30 P0 (critical severity), 135 P1 (high severity), 135 P2 (medium severity). (Total 270 P1/P2 + 30 P0 = 300).
     - No artificial `insufficient_evidence` outside explicit target.
   - Grounding: Vietnamese street coordinates and street names (Hanoi / Ho Chi Minh City bounds), documented route geometries, finite non-zero distances.
   - Actor Profiles: PII-free synthetic Vietnamese names, train/test driver split.
   - Determinism: Fixed generator seed and version, rerun hash equivalence verified.

4. **Preset Integration & Tenant Isolation:**
   - Expose `synthesized_vietnam_trip` via `src/services/test_presets.py`.
   - Never use corpus source fixture `org_id` to cross tenants; organization ownership MUST be assigned from the active authorized context on preset execution.

5. **Benchmarking & Publication:**
   - Benchmark with checksummed offline frozen detector (both strict and enum-blind modes) computing per-class Precision, Recall, F1, and severity confusion.
   - Stage release bundle under `data/benchmark-10k/releases_vietnam/` (or `data/benchmark-10k/profiles/synthesized_vietnam_trip/`).
   - If HF upload token is unavailable, report exact blocker and stage complete publish-ready CLI command.

---

## Tasks

### Task 1: Reconcile Existing Preset Metadata (TDD RED -> GREEN)
- [ ] Write failing test in `tests/unit/test_presets_reconciliation.py` asserting `PUBLISHED_CLASS_COUNTS` sums to exactly `PUBLISHED_TRIPS` (40,000) matching `manifest.json`.
- [ ] Update `src/services/test_presets.py` with exact counts from `manifest.json`.
- [ ] Verify test passes.

### Task 2: Profile Full 40k Hugging Face Corpus (`releases_v1`)
- [ ] Fetch `releases_v1/trips.jsonl` using `scripts/benchmark/fetch_dataset.py` and verify SHA-256 (`1a0f05b3...`).
- [ ] Build profiling script `scripts/benchmark/profile_40k.py` to analyze:
  - Geography breakdown (bounding boxes, country/city origin).
  - Schema conformance against `docs/architecture/schemas/` and `db/migrations`.
  - Class, severity, route-distance, and duration distributions.
- [ ] Document findings in `docs/data/SYNTHESIZED_VIETNAM_TRIP_394.md`.

### Task 3: Build Deterministic Vietnam Dataset Generator
- [ ] Implement `scripts/benchmark/synthesize_vietnam.py`:
  - 1,000 distinct trips.
  - 700 `no_violation`, 135 P1, 135 P2, 30 P0.
  - Realistic Vietnamese road coordinates and landmarks (Hanoi / Ho Chi Minh City).
  - Grounded telemetry points with timestamps, speeds, headings, and non-zero distance.
  - Clean train/test driver split (e.g. 80/20 driver partitioning).
  - Deterministic rerun guarantee: verify two runs with the same seed yield identical `trips_sha256`.
- [ ] Generate output files: `trips.jsonl`, `labels.csv`, `manifest.json`, `checksums.json`, `sample_100.jsonl`.
- [ ] Unit test generator in `tests/unit/test_vietnam_generator.py`.

### Task 4: Integrate Vietnam Preset in Services & Test Console
- [ ] Update `src/services/test_presets.py` to register `synthesized_vietnam_trip` preset.
- [ ] Ensure sample trips load from committed sample file offline.
- [ ] Enforce active context organization assignment on execution (prevent cross-tenant leaks).
- [ ] Write tests in `tests/unit/test_vietnam_preset.py` validating preset listing, selection, round-trip, finite geometry, and tenant binding.

### Task 5: Run Strict & Enum-Blind Frozen Offline Benchmarks
- [ ] Implement / extend benchmark evaluation in `scripts/benchmark/run_vietnam_benchmark.py`.
- [ ] Evaluate frozen detector on the 1,000-trip Vietnam corpus:
  - Strict mode (standard error enums).
  - Enum-blind mode (generalized anomaly scoring).
- [ ] Compute per-class Precision, Recall, F1 and severity confusion matrix.
- [ ] Record results, limitations, detector identity, and uncalibrated confidence notes in `docs/data/SYNTHESIZED_VIETNAM_TRIP_394.md`.

### Task 6: Stage HF Release & Update Documentation
- [ ] Stage complete release bundle in `data/benchmark-10k/profiles/synthesized_vietnam_trip/`.
- [ ] Check HF write credentials (`HF_TOKEN` / `~/.cache/huggingface/token`). Since absent, construct exact `python scripts/benchmark/publish_dataset.py` command and report blocker to conductor.
- [ ] Create `docs/data/SYNTHESIZED_VIETNAM_TRIP_394.md` detailing EDA, generation, validation, benchmark, and schema comparison.
- [ ] Update `data/benchmark-10k/STORAGE.md`, `docs/data/DATASET_CARDS.md`, and `docs/data/README.md`.
- [ ] Emit conductor release artifact `/tmp/greensentinel-vietnam-release.json`.

### Task 7: Verification & Final Checks
- [ ] Run focused test suites: `pytest tests/unit/test_presets_reconciliation.py tests/unit/test_vietnam_generator.py tests/unit/test_vietnam_preset.py`.
- [ ] Run `scripts/check.sh` (Ruff linter, formatter, typechecker, pytest).
- [ ] Commit changes with Conventional Commits, push branch, open PR referencing #394 and #400.
