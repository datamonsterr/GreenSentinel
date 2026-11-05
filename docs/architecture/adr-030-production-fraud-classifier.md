# ADR-030: Production Fraud Classifier Architecture (R3D Stacker)

## Status

Accepted for implementation; [issue #569](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/569) (Parent epic #494).

## Context

Production dispute triage and telemetry streaming require real-time fraud assessment across 7 operational fraud categories:
1. `normal`
2. `gps_spoofing`
3. `route_deviation`
4. `phantom_dropoff`
5. `fare_inflation`
6. `collusion`
7. `identity_compromise`

In research exploration (#494), direct LLM-only classification (e.g. Mercury, Gemini 2.5 Flash) on 6,000 trips achieved:
- Low discrimination: macro-F1 ~0.5155
- High latency: 1,500ms – 3,500ms per trip
- Cost barrier: $0.003 – $0.010 per trip evaluation
- Calibration instability and non-deterministic schema failure modes under load.

A three-stage hybrid machine learning pipeline was researched:
- **R3C (Tabular LightGBM)**: 37 leak-audited spatial, kinematic, and pricing features. Macro-F1: 0.8601. Inference: <1ms.
- **R3F (Sequence 1D-CNN)**: 7-channel 128-step normalized temporal trajectory + 6 static context features. Macro-F1: 0.7711. Captures fine-grained GPS breadcrumb jitter and telemetry freeze signatures.
- **R3D (Stacked Ensemble)**: LightGBM meta-learner combining calibrated probabilities from R3C and R3F, model cross-entropy, prediction disagreement, and static trip context. Dev300 macro-F1: 0.8688. Test-6000 macro-F1: 0.8680.

To productionise R3D under the system constraints of GreenSentinel, we must resolve runtime inference dependencies, serialization safety, model artifact delivery, telemetry normalization, and latency budgets.

## Decision

1. **Production Package Architecture**:
   - Implement `src/services/fraud_classifier/` as the single source of truth for feature extraction (`features_tabular.py`, `features_sequence.py`), guardrail short-circuiting (`guardrail.py`), artifact loading (`artifacts.py`), and inference orchestration (`model.py`).
   - The thread-safe singleton `get_fraud_classifier()` exposes `predict(bundle)` and vectorised `predict_many(bundles)`.
   - Output schema adheres strictly to `src.models.classifier.ClassifierResult`.

2. **Inference Runtime Engine (Zero PyTorch in Production)**:
   - Export R3F PyTorch 1D-CNN to ONNX (opset 17, dynamic batch axis) executed via CPU-optimized `onnxruntime` (1.31.0).
   - Export R3C and Stacker LightGBM models as native LightGBM text files (`booster.save_model`) loaded via `lightgbm.Booster(model_file=...)`.
   - Strictly prohibit Python `pickle` and `torch` in runtime dependencies (`requirements.txt`).

3. **Artifact Storage and Supply Chain**:
   - Public Hugging Face Hub model repository: `datamonsterr/green-sentinel-r3d-classifier`.
   - Immutable artifact resolution pinned by commit hash revision: `268003f795b2950893e9ef6a54b250dec13eeee6`.
   - Strict SHA256 integrity verification against `models/r3d/manifest.json`. Resolution hierarchy:
     1. `FRAUD_CLASSIFIER_ARTIFACT_DIR` environment override
     2. Container directory `/app/models/r3d`
     3. Local workspace directory `models/r3d`
     4. On-demand authenticated/public Hugging Face Hub download.
   - Any checksum mismatch or missing artifact fails closed via `ClassifierUnavailableError`.

4. **Decoupled Advisory LLM Role**:
   - Real-time queue admission and triage are owned exclusively by R3D (latency p95 < 5ms).
   - LLMs act asynchronously as non-blocking advisory copilots for deep narrative synthesis and customer dispute dialogue generation, never blocking the critical triage path.

## 6 Required Architecture Questions

### 1. System Topology
- **Client & Workers**: Next.js client and `telemetry_queue_worker` ingest trip events into Redis streams / FastAPI endpoints.
- **Backend Service**: `src.services.fraud_classifier` evaluates trips in-process without external RPC hops.
- **External Dependencies**: Artifacts are pulled once at Docker build time from Hugging Face Hub; zero external runtime network calls during inference.

### 2. State & Graph Lifecycle
- Input bundles are normalised from either raw trip bundles or `JevAssessmentInput` schemas.
- Feature extraction extracts 37 tabular features and (128, 7) resampled sequence arrays.
- Guardrails (`should_short_circuit`) evaluate system outages and telemetry gaps; if triggered, short-circuits to `guardrail_short_circuit=True`, `category="normal"`, `is_anomalous=False` without ML evaluation.
- When active, R3C and R3F infer probabilities in parallel, passing concatenation vectors to Stacker. Stacker outputs final 7-class distribution, entropy, and risk band.

### 3. Tool Contracts
- `FraudClassifier.predict(bundle: dict) -> ClassifierResult`
- `FraudClassifier.predict_many(bundles: list[dict]) -> list[ClassifierResult]`
- Inputs are scrubbed of all leakage keys (`fraud_label`, `ground_truth`, `dispute_outcome`).
- Exceptions raise `ClassifierUnavailableError` (missing artifacts) or `ValueError` (invalid input schema).

### 4. Data Flows
1. Telemetry event arrives via HTTP `/telemetry/assess` or background queue worker.
2. `normalise_bundle()` validates keys, extracts GPS breadcrumbs, and scrubs ground truth.
3. `should_short_circuit()` tests sensor/infrastructure validity.
4. Tabular and sequence feature extractors produce NumPy matrices.
5. `onnxruntime.InferenceSession` and `lightgbm.Booster` compute multi-class posteriors.
6. `stacker.txt` generates calibrated ensemble prediction.
7. `ClassifierResult` is returned with explicit `feature_ms` and `inference_ms` profiling metrics.

### 5. Architectural Trade-offs & Alternatives

| Option | Pros | Cons | Decision |
|---|---|---|---|
| **R3D Stacker (LightGBM + ONNX)** | Macro-F1 0.8680; p95 < 5ms; zero token cost; deterministic calibration | Requires multi-artifact packaging and ONNX export pipeline | **Selected** |
| **LLM-Only Prompting (Mercury / Gemini)** | Simple zero-shot prompt; no ML build pipeline | Macro-F1 0.5155; 2000ms+ latency; $0.005/trip; rate limits | Rejected |
| **PyTorch Full Runtime in Docker** | Direct loading of research `.pt` checkpoint | +200MB image bloat; Python GIL overhead; heavier cold start | Rejected |
| **Pickled Models (.pkl)** | Retains exact Python scikit-learn wrapper objects | Insecure arbitrary code execution risk; version-fragile | Rejected |

### 6. Security & Boundary Protection
- **No Pickles**: Models serialized purely as ONNX protobuf (`r3f.onnx`) and LightGBM text strings (`r3c.txt`, `stacker.txt`).
- **Integrity Gating**: Manifest SHA256 checksums verified before model instantiation. Corrupted weights trigger fail-closed behavior.
- **Leak Prevention**: Strict key scrubbing removes `fraud_label`, `disputed`, `label`, `resolution`, `settlement` before feature calculation.
- **Secrets Isolation**: Public Hugging Face repository requires no API keys during image build or local execution.

## Consequences

- **Performance**: In-process inference p95 is ~4.83ms (single trip) and ~30.06ms per trip in batches of 64, well within the 50ms SLA budget.
- **Docker Footprint**: Avoids PyTorch runtime dependencies. Incremental Docker image size delta is ~50MB (~43MB wheels + 6.8MB artifacts).
- **Parity**: Dev300 export parity test confirms 300/300 class matches and max absolute probability difference $\le 2.22 \times 10^{-16}$.

## Rollback & Fallback Procedure

If the fraud classifier must be disabled:
1. Set environment variable `FRAUD_CLASSIFIER_ENABLED=false`.
2. Telemetry ingestion worker and API triage endpoints immediately bypass the ML model and fallback to legacy heuristic rule evaluation.
3. Zero-downtime reconfiguration without redeploying container binaries.
