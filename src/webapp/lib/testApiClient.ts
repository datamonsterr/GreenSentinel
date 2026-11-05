/**
 * Isolated Test API Client — SPEC-0130 §6.7
 * Injects X-Test-Context: true header on all requests.
 * Routes exclusively to /test/api/v1/*.
 * MUST NEVER be used outside of /test/* routes.
 */

export type TestApiTokenProvider = () => Promise<string | null>;

let testTokenProvider: TestApiTokenProvider | null = null;
let tokenProviderWaiters: Array<() => void> = [];

export function setTestApiTokenProvider(provider: TestApiTokenProvider | null): void {
  testTokenProvider = provider;
  if (provider && tokenProviderWaiters.length > 0) {
    const waiters = tokenProviderWaiters;
    tokenProviderWaiters = [];
    for (const w of waiters) {
      w();
    }
  }
}

async function waitForTestTokenProvider(timeoutMs = 1500): Promise<TestApiTokenProvider | null> {
  if (testTokenProvider) return testTokenProvider;
  return new Promise((resolve) => {
    let timer: NodeJS.Timeout | null = null;
    const waiter = () => {
      if (timer) clearTimeout(timer);
      resolve(testTokenProvider);
    };
    timer = setTimeout(() => {
      tokenProviderWaiters = tokenProviderWaiters.filter((w) => w !== waiter);
      resolve(testTokenProvider);
    }, timeoutMs);
    tokenProviderWaiters.push(waiter);
  });
}

export function getTestApiBaseUrl(): string {
  if (typeof window !== "undefined") {
    const envUrl = process.env.NEXT_PUBLIC_API_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "";
    if (envUrl && !envUrl.includes("[SENSITIVE]") && !envUrl.includes("placeholder")) {
      if (envUrl.startsWith("http://") || envUrl.startsWith("https://")) {
        return `${envUrl.replace(/\/+$/, "")}/test/api/v1`;
      }
    }
  }
  return "/test/api/v1";
}

async function testAuthorizedHeaders(extraHeaders: Record<string, string> = {}): Promise<Headers> {
  const h = new Headers({
    "Content-Type": "application/json",
    "X-Test-Context": "true",
    "X-Role": "demo_operator",
    ...extraHeaders,
  });
  let provider = testTokenProvider;
  if (!provider) {
    provider = await waitForTestTokenProvider(1500);
  }
  let token: string | null = null;
  if (provider) {
    try {
      token = await provider();
    } catch {
      token = null;
    }
  }
  if (token) {
    h.set("Authorization", `Bearer ${token}`);
  }
  return h;
}

async function testRequestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = await testAuthorizedHeaders(
    (init.headers as Record<string, string>) ?? {}
  );
  const basePath = getTestApiBaseUrl();
  const res = await fetch(`${basePath}${path}`, { ...init, headers });
  if (!res.ok) {
    const err = await res.text().catch(() => res.statusText);
    throw new Error(`Test API ${res.status}: ${err}`);
  }
  return res.json() as Promise<T>;
}

export async function postTest<T>(path: string, body: unknown): Promise<T> {
  return testRequestJson<T>(path, { method: "POST", body: JSON.stringify(body) });
}

export async function streamTest(path: string, signal?: AbortSignal): Promise<Response> {
  const headers = await testAuthorizedHeaders({ Accept: "text/event-stream" });
  const basePath = getTestApiBaseUrl();
  const res = await fetch(`${basePath}${path}`, { headers, signal });
  if (!res.ok) throw new Error(`Test API ${res.status}: ${await res.text().catch(() => res.statusText)}`);
  return res;
}

export interface TestActorOption { id: string; display_name: string }
export interface TestActorDirectory {
  drivers: TestActorOption[];
  passengers: TestActorOption[];
  vehicles: TestActorOption[];
  policies: TestActorOption[];
}

export async function fetchTestActors(): Promise<TestActorDirectory> {
  return testRequestJson<TestActorDirectory>("/actors");
}

// --- Types ---
export type CaseStatus = "OPEN" | "UNDER_REVIEW" | "CLOSED";
export type TriageDecision = "INVESTIGATE" | "APPROVE_LEGITIMATE";

export interface TestCase {
  id: string;
  trip_id: string | null;
  run_id: string | null;
  risk_score: number;
  anomaly_types: string[];
  status: CaseStatus;
  created_at: string;
}

export interface TriageRequest {
  decision: TriageDecision;
  rationale: string;
  lease_id?: string;
}

export interface TriageResponse {
  case_id: string;
  decision: string;
  new_status: string;
  rationale: string;
  audit_event_id: string;
  timestamp: string;
}

export interface TestSample {
  run_id: string;
  step_index: number;
  latitude: number;
  longitude: number;
  speed_mps: number;
  heading_deg: number;
  is_fault_injected: boolean;
  fault_type: string | null;
  emitted_at: string;
}

export interface TestNotification {
  id: string;
  run_id: string;
  recipient_type: string;
  recipient_id: string;
  channel: string;
  body: string;
  intercepted_at: string;
}

// --- Case API ---
export interface CaseFilters {
  run_id?: string;
  trip_id?: string;
  status?: CaseStatus;
  anomaly_types?: string[];
  risk_score_min?: number;
}

export async function fetchTestCases(filters: CaseFilters = {}): Promise<TestCase[]> {
  const params = new URLSearchParams();
  if (filters.run_id) params.set("run_id", filters.run_id);
  if (filters.trip_id) params.set("trip_id", filters.trip_id);
  if (filters.status) params.set("status", filters.status);
  if (filters.anomaly_types?.length) params.set("anomaly_types", filters.anomaly_types.join(","));
  if (filters.risk_score_min != null) params.set("risk_score_min", String(filters.risk_score_min));
  const qs = params.toString() ? `?${params}` : "";
  return testRequestJson<TestCase[]>(`/cases${qs}`);
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function fetchTestCaseDetail<T = any>(caseId: string): Promise<T> {
  return testRequestJson<T>(`/cases/${encodeURIComponent(caseId)}/detail`);
}

export async function triageCase(caseId: string, body: TriageRequest): Promise<TriageResponse> {
  return testRequestJson<TriageResponse>(`/cases/${encodeURIComponent(caseId)}/triage`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function fetchTestSamples(runId: string, limit = 500): Promise<TestSample[]> {
  return testRequestJson<TestSample[]>(`/runs/${encodeURIComponent(runId)}/samples?limit=${limit}`);
}

export async function fetchTestRunStatus(runId: string) {
  return testRequestJson<{ id: string; status: string; current_step: number; total_steps: number }>(`/runs/${encodeURIComponent(runId)}`);
}

export async function fetchTestNotifications(runId: string): Promise<TestNotification[]> {
  return testRequestJson<TestNotification[]>(`/runs/${encodeURIComponent(runId)}/notifications`);
}

export interface RouteLegDetails {
  coordinates: [number, number][];
  distance_m: number;
  duration_s: number;
  provider: string;
}

export interface RouteWaypoint {
  lon: number;
  lat: number;
  leg: "pickup" | "destination";
  name?: string;
  id?: string;
}

export interface RouteResolveResponse {
  route_geometry: {
    type: "LineString" | "MultiLineString";
    coordinates: [number, number][] | [number, number][][];
  };
  pickup_route: RouteLegDetails;
  destination_route: RouteLegDetails;
  provider: string;
  waypoints?: RouteWaypoint[];
  max_start_to_pickup_m?: number;
}

export async function resolveTestRoute(
  origin: [number, number],
  pickup: [number, number],
  destination: [number, number],
  waypoints?: [number, number][] | RouteWaypoint[]
): Promise<RouteResolveResponse> {
  return postTest<RouteResolveResponse>("/routes/resolve", {
    origin,
    pickup,
    destination,
    waypoints: waypoints ?? [],
  });
}

export async function saveSimulationCase(
  runId: string,
  options?: { riskScore?: number; anomalyTypes?: string[] }
): Promise<TestCase> {
  return postTest<TestCase>(`/runs/${encodeURIComponent(runId)}/save-case`, {
    risk_score: options?.riskScore,
    anomaly_types: options?.anomalyTypes,
  });
}

export interface GeocodeLocation {
  formatted: string;
  lat: number;
  lon: number;
  address_line1?: string | null;
  city?: string | null;
}

export interface ProductionPublishResult {
  status: string;
  run_id: string;
  trip_id: string;
  case_id: string;
  destination: string;
}

export async function searchGeocode(text: string, limit = 5): Promise<GeocodeLocation[]> {
  const qs = new URLSearchParams({ text, limit: String(limit) });
  const res = await testRequestJson<{ results: GeocodeLocation[] }>(`/geocode?${qs.toString()}`);
  return res.results || [];
}

export interface PublishProductionPayload {
  points?: Array<{
    latitude: number;
    longitude: number;
    speed_mps: number;
    heading_deg: number;
    occurred_at: string;
    status?: string;
  }>;
  pickup?: { coordinates: [number, number] };
  dropoff?: { coordinates: [number, number] };
  pickup_address?: string;
  dropoff_address?: string;
  messages?: Array<{
    role: "driver" | "customer";
    text: string;
    offset_seconds: number;
  }>;
  driver_id?: string;
  passenger_id?: string;
  vehicle_id?: string;
  policy_version_id?: string;
  vehicle_plate?: string;
  speed_mps?: number;
}

export async function publishSimulationToProduction(
  runId: string,
  payload?: PublishProductionPayload
): Promise<ProductionPublishResult> {
  return postTest<ProductionPublishResult>(
    `/runs/${encodeURIComponent(runId)}/publish-production`,
    payload ?? {}
  );
}

// --- Console history, title, overview ---
export interface TestRunSummary {
  id: string;
  title: string | null;
  status: string;
  trip_id: string | null;
  created_at: string;
  completed_at: string | null;
  cancellation_actor: string | null;
  cancellation_reason: string | null;
  source?: "manual" | "preset" | "preset_batch" | string | null;
  expected_label?: string | null;
  predicted_label?: string | null;
  error_type?: string | null;
  confidence?: number | null;
  case_id?: string | null;
  license_plate?: string | null;
  driver_name?: string | null;
  origin_address?: string | null;
  pickup_address?: string | null;
  destination_address?: string | null;
}

export interface TestRun {
  id: string;
  definition_revision_id: string;
  status: string;
  current_step: number;
  total_steps: number;
  simulation_clock: string;
  speed_factor: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  title: string | null;
  trip_id: string | null;
  cancelled_at: string | null;
  cancellation_actor: string | null;
  cancellation_reason: string | null;
}

export async function fetchTestRuns(limit = 50): Promise<TestRunSummary[]> {
  return testRequestJson<TestRunSummary[]>(`/runs?limit=${limit}`);
}

export async function updateTestRunTitle(runId: string, title: string): Promise<TestRun> {
  return testRequestJson<TestRun>(`/runs/${encodeURIComponent(runId)}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}

export interface PipelineStage {
  key: string;
  label: string;
  count: number;
  state: "done" | "active" | "waiting" | "unknown";
}

export interface TestRunOverview {
  run_id: string;
  status: string;
  trips_input: number;
  trips_processed: number;
  trips_classified: number;
  classification_counts: Record<string, number>;
  stages: PipelineStage[];
}

export async function fetchTestRunOverview(runId: string): Promise<TestRunOverview> {
  return testRequestJson<TestRunOverview>(`/runs/${encodeURIComponent(runId)}/overview`);
}

export type CancellationActor = "passenger" | "driver";

export interface TestControlResult {
  status: string;
  command: string;
}

export async function controlTestRun(
  runId: string,
  command: string,
  payload: Record<string, unknown> = {}
): Promise<TestControlResult> {
  return postTest<TestControlResult>(`/runs/${encodeURIComponent(runId)}/controls`, { command, payload });
}

/** Participant-initiated early termination. The reason is required and trimmed server-side. */
export async function cancelTestRun(
  runId: string,
  actor: CancellationActor,
  reason: string
): Promise<TestControlResult> {
  const trimmed = reason.trim();
  if (!trimmed) {
    throw new Error("A cancellation reason is required");
  }
  return controlTestRun(runId, "CANCEL", { actor, reason: trimmed });
}

// --- Preset trip library ---
export interface TestPresetTrip {
  trip_ref: string;
  label: string;
  source: string | null;
  pickup_name: string | null;
  dropoff_name: string | null;
  driver_display_name: string | null;
  driver_name?: string | null;
  license_plate?: string | null;
  city?: string | null;
  severity?: string | null;
  scenario?: string | null;
  distance_m: number | null;
  duration_s: number | null;
  telemetry_points: number;
  cancellation_actor: string | null;
  cancellation_reason: string | null;
}

export interface TestPreset {
  id: string;
  title: string;
  description: string;
  kind: "default" | "normal" | "wrong_direction" | "violation" | "vietnam";
  available: boolean;
  unavailable_reason: string | null;
  source_label: string | null;
  selection_size: number | null;
  available_trips: number | null;
  metadata: Record<string, unknown>;
  metrics: Record<string, unknown>;
  sample_trips: TestPresetTrip[];
}

export interface TestPresetListResponse {
  presets: TestPreset[];
  source: Record<string, unknown>;
}

export interface TestPresetPlanResponse {
  plan: {
    id: string;
    name: string;
    description: string | null;
    created_at: string;
    updated_at: string;
  };
  definition: {
    id: string;
    plan_id: string;
    revision_number: number;
    route_geometry: {
      type: "LineString";
      coordinates: [number, number][];
    };
    driver_config: {
      driver_id: string;
      speed_mps: number;
      update_cadence_s: number;
    };
    passenger_config: {
      passenger_id: string;
      name: string;
    };
    fault_configs: unknown[];
    messages: {
      sender_role: "DRIVER" | "PASSENGER" | "SYSTEM";
      content: string;
      offset_seconds: number;
    }[];
    initial_snapshot: { location: { latitude: number; longitude: number }; address?: string | null } | null;
    pickup_snapshot: { location: { latitude: number; longitude: number }; address?: string | null } | null;
    destination_snapshot: { location: { latitude: number; longitude: number }; address?: string | null } | null;
  };
  preset_id: string;
  trip_ref: string;
  label: string;
  distance_m: number;
  telemetry_points: number;
  initial_snapshot: { location: { latitude: number; longitude: number }; address?: string | null } | null;
  pickup_snapshot: { location: { latitude: number; longitude: number }; address?: string | null } | null;
  destination_snapshot: { location: { latitude: number; longitude: number }; address?: string | null } | null;
  telemetry: Array<{
    occurred_at: string;
    latitude: number;
    longitude: number;
    speed_mps: number;
    heading_deg: number;
  }>;
}

export async function fetchTestPresets(sampleLimit = 5): Promise<TestPresetListResponse> {
  return testRequestJson<TestPresetListResponse>(`/presets?sample_limit=${sampleLimit}`);
}

export async function planTestPreset(
  presetId: string,
  tripRef?: string,
  title?: string
): Promise<TestPresetPlanResponse> {
  return postTest<TestPresetPlanResponse>("/presets/plan", {
    preset_id: presetId,
    trip_ref: tripRef,
    title,
  });
}

// --- Extended Preset Detail & Distributions ---
export interface GroupedLabelCounts {
  fraud: number;
  no_violation: number;
  insufficient_evidence: number;
  grouped?: Record<string, number>;
  per_code?: Record<string, number>;
}

export interface PresetDistributions {
  total_records: number;
  by_label: GroupedLabelCounts;
  per_code: Record<string, number>;
  by_severity: Record<string, number>;
  by_scenario: Record<string, number>;
  by_city: Record<string, number>;
  by_cancellation_actor: Record<string, number>;
}

export interface TestPresetDetailResponse extends TestPreset {
  source_release?: string | null;
  revision?: string | null;
  trips_sha256?: string | null;
  license?: string | null;
  trip_count: number;
  published_release_counts?: Record<string, unknown>;
  distributions: PresetDistributions;
  info?: Record<string, unknown>;
}

export async function fetchTestPresetDetail(presetId: string, sampleLimit = 20): Promise<TestPresetDetailResponse> {
  return testRequestJson<TestPresetDetailResponse>(`/presets/${encodeURIComponent(presetId)}?sample_limit=${sampleLimit}`);
}

// --- Clerk Linked Drivers ---
export interface ClerkLinkedDriver {
  driver_id: string;
  display_name: string;
  email: string;
  principal_id: string;
  vehicle_id?: string | null;
  license_plate?: string | null;
}

export async function fetchClerkLinkedDrivers(): Promise<ClerkLinkedDriver[]> {
  return testRequestJson<ClerkLinkedDriver[]>("/drivers/linked");
}

// --- Preset Batch Runs ---
export interface PresetBatchRunCreate {
  trip_limit?: number | null;
  trips_per_batch: number;
  interval_s: number;
  driver_ids: string[];
}

export interface PresetBatchTrip {
  id: string;
  batch_id: string;
  trip_ref: string;
  order: number;
  status: string;
  driver_id?: string | null;
  driver_name?: string | null;
  expected_label?: string | null;
  predicted_label?: string | null;
  confidence?: number | null;
  case_id?: string | null;
  run_id?: string | null;
  error?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  snapshot?: Record<string, unknown>;
}

export interface PresetBatchRunResponse {
  id: string;
  organization_id: string;
  preset_id: string;
  params: Record<string, unknown>;
  status: string;
  counters: Record<string, number>;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
}

export interface PresetBatchRunDetailResponse extends PresetBatchRunResponse {
  trips: PresetBatchTrip[];
}

export interface PresetBatchEvent {
  event_id: string;
  event_type: string;
  batch_id: string;
  trip_ref?: string | null;
  driver_id?: string | null;
  driver_name?: string | null;
  reached_classifier?: boolean;
  occurred_at: string;
  label?: string | null;
  confidence?: number | null;
  case_id?: string | null;
  reason?: string | null;
  data?: Record<string, unknown>;
}

export async function createPresetBatchRun(presetId: string, payload: PresetBatchRunCreate): Promise<PresetBatchRunResponse> {
  return postTest<PresetBatchRunResponse>(`/presets/${encodeURIComponent(presetId)}/runs`, payload);
}

export async function fetchPresetBatchRunDetail(batchId: string): Promise<PresetBatchRunDetailResponse> {
  return testRequestJson<PresetBatchRunDetailResponse>(`/presets/runs/${encodeURIComponent(batchId)}`);
}

export async function cancelPresetBatchRun(batchId: string): Promise<PresetBatchRunResponse> {
  return postTest<PresetBatchRunResponse>(`/presets/runs/${encodeURIComponent(batchId)}/cancel`, {});
}


// --- Run Trace & Pipeline Stages (SPEC-0130 §6.7 / Issue #459) ---
export interface TestRunTraceStage {
  stage: string;
  state: "done" | "waiting" | "skipped" | "active" | "pending";
  occurred_at: string | null;
  detail: Record<string, unknown> | string | null;
}

export async function fetchRunTrace(runId: string): Promise<TestRunTraceStage[]> {
  return testRequestJson<TestRunTraceStage[]>(`/runs/${encodeURIComponent(runId)}/trace`);
}

export type ExpectedLabel =
  | "no_violation"
  | "ERR-01"
  | "ERR-02"
  | "ERR-03"
  | "ERR-04"
  | "ERR-05"
  | "insufficient_evidence";

export async function searchClerkDrivers(email: string): Promise<ClerkLinkedDriver[]> {
  const qs = new URLSearchParams({ email });
  return testRequestJson<ClerkLinkedDriver[]>(`/drivers/search?${qs.toString()}`);
}
