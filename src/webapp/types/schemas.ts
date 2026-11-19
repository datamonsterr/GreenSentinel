/**
 * TypeScript types strictly matching docs/architecture/schemas:
 * 1. domain-event.schema.json
 * 2. telemetry-event.schema.json
 */

export type DomainEventType =
  | "trip.requested"
  | "assignment.offered"
  | "assignment.accepted"
  | "traffic.observed"
  | "passenger.cancelled"
  | "passenger.feedback_submitted"
  | "driver.explanation_submitted"
  | "case.evidence_updated"
  | "assessment.completed"
  | "case.ready"
  | "case.adjudicated"
  | "sanction.approved"
  | "telemetry.gap_alert";

export type AggregateType =
  | "trip"
  | "assignment"
  | "case"
  | "assessment"
  | "sanction";

export type ActorType =
  | "passenger"
  | "driver"
  | "analyst"
  | "service"
  | "simulator";

export interface EventActor {
  type: ActorType;
  id: string;
}

export interface EventMetadata {
  producer?: string;
  trace_id?: string | null;
  simulation_run_id?: string | null;
}

export interface DomainEvent<TPayload = Record<string, unknown>> {
  schema_version: 1;
  event_id: string; // UUID format
  event_type: DomainEventType;
  aggregate_type: AggregateType;
  aggregate_id: string; // UUID format
  aggregate_version: number;
  occurred_at: string; // ISO 8601 date-time
  correlation_id: string; // UUID format
  causation_id?: string | null;
  actor: EventActor;
  payload: TPayload;
  metadata?: EventMetadata;
}

export type TelemetryEventType =
  | "telemetry.observed"
  | "driver.app_crashed"
  | "driver.network_changed"
  | "telemetry.missingness_alert";

export type AppState = "foreground" | "background" | "crashed" | "unknown";
export type NetworkState = "online" | "offline" | "degraded" | "unknown";
export type GpsState = "valid" | "jitter" | "unavailable" | "mock_reported" | "unknown";

export interface GeoPosition {
  latitude: number;
  longitude: number;
  accuracy_m: number | null;
}

export interface TelemetryPayload {
  position: GeoPosition | null;
  speed_mps?: number | null;
  bearing_deg?: number | null;
  app_state: AppState;
  network_state: NetworkState;
  gps_state: GpsState;
  mock_location_reported?: boolean | null;
  latency_ms?: number | null;
  distance_to_pickup_m?: number | null;
  davi_score?: number | null;
  data_gap_s?: number | null;
}

export interface RouteCandidate {
  id: string;
  name: string;
  type: "shortest" | "arterial" | "detour";
  rank: 1 | 2 | 3;
  distance_m: number;
  duration_s: number;
  davi: number;
  sdd: number;
  traffic_signals_count: number;
  congestion_level: "clear" | "moderate" | "heavy";
  coordinates: [number, number][]; // [lon, lat][]
  color: string;
}

export interface PeerDriverObservation {
  driver_id: string;
  vehicle_plate: string;
  speed_kmh: number;
  passed_at: string;
  status: string;
}

export interface TrafficCorroboration {
  road_segment: string;
  observed_at: string;
  suspect_driver: {
    driver_id: string;
    speed_kmh: number;
    stall_duration_s: number | null;
    claimed_reason: string;
  };
  peer_drivers: PeerDriverObservation[];
  public_service: {
    provider: string; // e.g. "Google Maps Traffic"
    average_speed_kmh: number;
    congestion: "clear" | "moderate" | "heavy";
    signal_status: string;
  };
  verdict: "refuted" | "corroborated" | "inconclusive";
  verdict_detail: string;
}

export interface TimelineMilestone {
  id: string;
  timestamp: string;
  sequence?: number;
  type: "start_match" | "driver_arrived" | "pickup" | "dropoff_destination" | "stall_anomaly" | "gap_anomaly" | "speed_anomaly";
  title: string;
  description: string;
  lat?: number;
  lon?: number;
  speed_mps?: number;
  latency_ms?: number;
  davi?: number;
  is_anomaly?: boolean;
}

export interface DataMissingnessAlert {
  alert_id: string;
  start_time: string;
  end_time: string;
  gap_duration_s: number;
  reason: string;
  severity: "warning" | "critical";
}

export interface TelemetryEvent {
  schema_version: 1;
  event_id: string; // UUID
  event_type: TelemetryEventType;
  source: string;
  occurred_at: string; // ISO 8601
  correlation_id: string; // UUID
  causation_id?: string | null;
  simulation_run_id?: string | null;
  trip_id: string; // UUID
  assignment_id: string; // UUID
  driver_id: string; // UUID
  sequence: number;
  payload: TelemetryPayload;
}

/**
 * UI Specific Adjudication Model incorporating Domain & Telemetry contracts
 */
export interface AdjudicationCase {
  id: string;
  case_token: string;
  trip_id: string;
  assignment_id: string;
  driver_id: string;
  driver_name: string;
  vehicle_plate: string;
  severity: "P0" | "P1" | "P2";
  locked_by?: string | null;
  sla_countdown_s: number;
  initial_sla_budget_s: number;
  stall_duration_s: number | null;
  davi_drift: number;
  pickup_address: string;
  dropoff_address: string;
  fare_amount_vnd: number;
  dispute: {
    driver_explanation?: DomainEvent<{
      explanation_text: string;
      reason_code?: string;
    }>;
    passenger_cancel?: DomainEvent<{
      cancellation_reason: string;
      satisfaction_score?: number;
    }>;
  };
  telemetry_points: TelemetryEvent[];
  ai_assessment?: DomainEvent<{
    confidence_pct: number;
    primary_violation_code: "ERR-01" | "ERR-02" | "ERR-03" | "ERR-04" | "ERR-05";
    recommended_sanction: string;
    rationale: string;
    policy_citation: string;
  }>;
}

/**
 * Backend API Models strictly matching src/models/schemas.py & src/api/routes.py
 */

export interface FraudCaseSummary extends StagedAdjudicationContext {
  id: string;
  trip_id?: string | null;
  assignment_id?: string | null;
  driver_id?: string | null;
  status: string;
  priority: string;
  priority_score: number;
  category?: string | null;
  confidence?: number | null;
  opened_at?: string | null;
  updated_at?: string | null;
  assigned_analyst_id?: string | null;
  active_lease_analyst_id?: string | null;
  active_lease_expires_at?: string | null;
  version: number;
  driver_name?: string | null;
  vehicle_plate?: string | null;
  district?: string | null;
  stall_duration_s?: number | null;
  sla_countdown_s?: number | null;
  assigned_analyst_name?: string | null;
  dispute_status?: string | null;
  dispute_deadline?: string | null;
}

export interface CaseListResponse {
  items: FraudCaseSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface GeoJsonPoint {
  type?: string;
  coordinates?: [number, number] | number[];
}

export interface TripDetail {
  id?: string | null;
  status?: string;
  pickup?: GeoJsonPoint | Record<string, any> | null;
  dropoff?: GeoJsonPoint | Record<string, any> | null;
  pickup_address?: string;
  dropoff_address?: string;
  district?: string | null;
  match_type?: "now" | "auto" | string;
  fare_amount_vnd?: number | null;
  driver_name?: string;
  driver_avatar_url?: string;
  vehicle_plate?: string;
  vehicle_type?: string | null;
  driver_status?: string;
  rating?: number;
  acceptance_rate?: number;
  cancellation_rate?: number;
  total_trips?: number;
  past_warnings?: number;
  driver_statement?: string;
  passenger_statement?: string;
  cancellation_reason?: string | null;
  cancellation_actor?: string | null;
  driver_ref?: string | null;
  vehicle_model?: string | null;
  assignment_state?: string | null;
  requested_at?: string | null;
  arrived_at?: string | null;
  ended_at?: string | null;
  completed_at?: string | null;
  [key: string]: any;
}

export interface ForensicAbnormality {
  code: string;
  category: "telemetry" | "feature" | "incident" | "guardrail" | "trip";
  severity: "info" | "warning" | "critical";
  label: string;
  observed_value: string;
  description: string;
  evidence_source: string;
}

export interface ForensicBriefResponse {
  case_id: string;
  trip_id?: string | null;
  assignment_id?: string | null;
  driver_id?: string | null;
  suspected_category?: string | null;
  generated_at: string;
  abnormality_count: number;
  abnormalities: ForensicAbnormality[];
  summary_text: string;
  evidence_sources: string[];
  motivation_assessment?: DriverMotivationAssessment;
}

export interface DriverMotivationAssessment {
  economic_incentive_reward: number;
  intent_profile: "possible_accidental" | "possible_intentional_exploit" | "unclear_insufficient_data";
  natural_vietnamese_narrative: string;
}

export interface CasePolicyClause {
  id: string;
  section_ref: string;
  content: string;
  source_ref: string;
  category: string;
  source_url: string;
  relevance_score?: number | null;
}

export interface CasePolicyResponse {
  case_id: string;
  suspected_category?: string | null;
  policy_version_id?: string | null;
  policy_version?: string | null;
  effective_from?: string | null;
  action_matrix: Record<string, any>;
  applicable_action_rule: Record<string, any>;
  clauses: CasePolicyClause[];
  related_policies: Array<Record<string, any>>;
  source: string;
}

export interface CaseDetailResponse {
  conversation?: Array<{role:"driver"|"customer";text:string;occurred_at:string|null}>;
  case: FraudCaseSummary;
  trip?: TripDetail;
  telemetry_samples?: Array<Record<string, any>>;
  features?: Record<string, any> | null;
  assessment?: {
    id?: string | null;
    category?: string | null;
    confidence?: number | null;
    score_semantics?: string | null;
    reason_codes?: string[] | null;
    forensic_brief?: string | null;
  } | null;
  forensic_brief?: ForensicBriefResponse | null;
  case_policy?: CasePolicyResponse | null;
  route_geometry?: Record<string, any> | null;
  candidate_routes?: RouteCandidate[];
  traffic_corroboration?: TrafficCorroboration | null;
  timeline_milestones?: TimelineMilestone[];
  missingness_alerts?: DataMissingnessAlert[];
  destination?: { latitude: number; longitude: number; label?: string } | null;
  guardrails?: {
    is_blocking?: boolean;
    blocking_reasons?: string[];
  } | null;
  active_lease?: {
    analyst_id?: string;
    expires_at?: string;
  } | null;
  adjudication?: CaseAdjudication | null;
  preliminary_judgment?: PreliminaryJudgment | null;
  /** Measured corroboration and assessed intent supplied by the case service. */
  cockpit_evidence?: {
    ambient?: Record<string, unknown> | null;
    probe?: Record<string, unknown> | null;
    sensor_reliability?: Record<string, unknown> | null;
    stall_davi?: Record<string, unknown> | null;
    stall_davi_points?: Array<Record<string, unknown>> | null;
    motivation?: string | null;
    motivation_assessment?: string | null;
    willingness?: string | null;
    willingness_assessment?: string | null;
  } | null;
  workflow_draft?: { text: string; version: number; updated_at?: string | null; updated_by?: string | null; summary?: string; draft?: string } | null;
}

export type PreliminaryJudgmentChoice = "Nghi ngờ vi phạm" | "Nghi oan-bất khả kháng" | "Chưa đủ cơ sở";
export interface PreliminaryJudgment {
  id: string;
  case_id: string;
  analyst_id: string;
  judgment: PreliminaryJudgmentChoice;
  note?: string | null;
  created_at: string;
}

export interface AISuggestion {
  category?: string | null;
  confidence?: number | null;
  recommended_action?: string | null;
}

export interface StagedAdjudicationContext {
  preliminary_judgment_id?: string | null;
  preliminary_judgment?: PreliminaryJudgment | null;
  ai_suggestion?: AISuggestion | null;
  delta?: "match" | "mismatch" | null;
}

export interface CaseAdjudication extends Partial<AdjudicationResponse> {
  id?: string;
  analyst_id?: string;
  rationale?: string;
  approved_at?: string;
}

export interface ClaimCaseRequest {
  analyst_id: string;
  lease_duration_seconds?: number;
  role?: string;
  force?: boolean;
}

export interface ClaimCaseResponse {
  case_id: string;
  analyst_id: string;
  lease_expires_at: string;
  status: string;
}

export interface ReleaseCaseRequest {
  analyst_id: string;
  role?: string;
  force?: boolean;
  reason?: string;
}

export interface ReleaseCaseResponse {
  case_id: string;
  analyst_id: string;
  status: string;
  released_at: string;
}

export type CaseActionType = "REQUEST_EVIDENCE" | "ESCALATE" | "DEFER";

export interface CaseActionRequest {
  action_type: CaseActionType;
  analyst_id: string;
  notes?: string | null;
}

export interface CaseActionResponse {
  case_id: string;
  action_type: string;
  status: string;
  recorded_at: string;
  new_case_status: string;
}

export type AdjudicationOutcome = "AGREE" | "DISAGREE";

export interface AdjudicationRequest {
  outcome: AdjudicationOutcome;
  analyst_id: string;
  rationale: string;
  expected_case_version: number;
  policy_version_id?: string | null;
  snapshot_hash?: string | null;
  agent_turn_id?: string | null;
  preliminary_judgment_id?: string | null;
}

export interface ObservabilitySummary {
  scope: string;
  process_started_at: string;
  run_count: number;
  latency_ms: { sample_count: number; p50: number | null; p95: number | null };
  runs: { error_count: number; timeout_count: number; sample_count: number };
  tools: {
    call_count: number;
    success_count: number;
    failure_count: number;
    sample_count: number;
    success_rate_pct: number | null;
  };
  model: {
    name: string;
    input_tokens: number | null;
    output_tokens: number | null;
    token_sample_count: number;
    estimated_cost_usd: string | null;
    priced_sample_count: number;
    active_prompt_version: string;
  };
  quality: {
    grounding_error_count: number | null;
    grounding_sample_count: number;
    guardrail_violation_count: number | null;
    guardrail_sample_count: number;
  };
  benchmark: {
    status: "available" | "unavailable";
    sample_count: number;
    timestamp?: string | null;
    dataset_version: string | null;
    current_dataset_version: string | null;
    artifact_version: string | null;
    dataset_path: string;
    result_path: string;
    benchmark_model_version: string | null;
    benchmark_prompt_version: string | null;
    metrics: Record<string, number>;
  };
  tracing: {
    provider: string;
    project: string;
    project_url: string;
    enabled: boolean;
    environment: string;
  };
}

export interface AdjudicationResponse extends StagedAdjudicationContext {
  case_id: string;
  outcome: string;
  status: string;
  sanction_applied?: string | null;
  adjudicated_at: string;
  new_version: number;
}

export interface SimulationTriggerRequest {
  analyst_id?: string | null;
  seed?: number | null;
}

export interface SimulationTriggerResponse {
  scenario: string;
  case_id: string;
  status: string;
}

export interface CaseProgressEvent {
  case_id: string;
  status: string;
  progress: number;
  message: string;
  timestamp: string;
}

export interface PolicyCitationEvent {
  source: string;
  section: string;
  content: string;
}

export interface PolicyDeltaEvent {
  delta: string;
}

export interface PolicyDoneEvent {
  status: string;
}

export interface PolicyChatAttachment {
  name: string;
  media_type: "image/png" | "image/jpeg" | "image/webp";
  data_base64: string;
}

export interface PolicyChatRequest {
  query: string;
  case_id: string;
  turn_id: string;
  event_schema_version?: "1.0" | "1.1";
  reset_context?: boolean;
  attachments?: PolicyChatAttachment[];
}

export interface AgentSessionMessage {
  id: string;
  turn_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface AgentSessionResponse {
  session_id: string | null;
  messages: AgentSessionMessage[];
}

export interface ChatRequest {
  message: string;
}

export interface ChatResponse {
  response: string;
  analysis: string;
}

export interface HealthResponse {
  status: string;
  env: string;
  database: string;
}

/**
 * Driver Dispute and Autonomous Exoneration Types (Slice 3)
 */
export interface DriverDisputeContextResponse {
  case_id: string;
  driver_id: string;
  driver_name: string;
  trip_id: string;
  violation_code: string;
  violation_title: string;
  alleged_time: string | null;
  alleged_location: string | Record<string, any> | null;
  dispute_deadline: string | null;
  dispute_status: string;
  allowed_claim_types: string[];
}

export interface DriverCaseSessionItem {
  case_id: string;
  case_code?: string;
  driver_id?: string;
  driver_name?: string;
  violation_code: string;
  violation_title: string;
  dispute_status: string;
  status?: string;
  dispute_deadline?: string | null;
  created_at?: string;
  alleged_time?: string | null;
  alleged_location?: string | Record<string, any> | null;
  description?: string | null;
  trip_id?: string | null;
  vehicle_plate?: string | null;
  pickup_address?: string | null;
  dropoff_address?: string | null;
  source?: string;
  has_unread?: boolean;
}

export interface DriverCaseListResponse {
  items: DriverCaseSessionItem[];
  total: number;
}

export interface DriverTripRatingItem {
  stars?: number | null;
  comment?: string | null;
  locale?: string | null;
  created_at?: string | null;
}

export interface DriverTripItem {
  trip_id: string;
  driver_id?: string | null;
  organization_id?: string | null;
  pickup_label: string;
  pickup_lat?: number | null;
  pickup_lng?: number | null;
  dropoff_label: string;
  dropoff_lat?: number | null;
  dropoff_lng?: number | null;
  started_at: string;
  ended_at?: string | null;
  distance_km: number;
  duration_min: number;
  fare_vnd: number;
  payment_method: string;
  payment_method_synthetic?: boolean;
  rating?: DriverTripRatingItem | null;
  status: string;
  has_case: boolean;
  case_id?: string | null;
}

export interface DriverTripCounts {
  all: number;
  completed: number;
  flagged: number;
}

export interface DriverTripsResponse {
  trips: DriverTripItem[];
  /** Total trips matching the driver/status/month filter, independent of cursor. */
  total: number;
  next_cursor?: string | null;
  /** Per-status counts (all/completed/flagged) scoped by driver+month, ignoring `status`. Source of truth for tab badges. */
  counts: DriverTripCounts;
}

export interface DriverTripsSummaryResponse {
  month?: string | null;
  /** Total trips in the month, all statuses (not completed-only). */
  trip_count: number;
  total_fare_vnd: number;
  total_distance_km: number;
  avg_rating?: number | null;
}


export interface DriverChatRequest {
  case_id: string;
  driver_id: string;
  message: string;
  claim_type?: string;
  turn_id?: string;
  event_schema_version?: "1.0" | "1.1";
}

export interface DriverChatResponse {
  case_id: string;
  driver_id: string;
  reply: string;
  dispute_status: string;
  is_auto_dismissed: boolean;
  exoneration_receipt?: Record<string, any> | null;
  needs_analyst_review: boolean;
}

export interface AnalystDelegateInquiryRequest {
  case_id: string;
  analyst_id: string;
  instruction: string;
  deadline_hours?: number;
}

export interface DisputeDossierResponse {
  case_id: string;
  driver_id: string;
  driver_name: string;
  dispute_status: string;
  driver_statement: string | null;
  claim_type: string | null;
  traffic_corroboration: Record<string, any>;
  precedent_score: number;
  recommended_action: string;
  transcript: Array<{
    role: string;
    content?: string;
    text?: string;
    timestamp?: string;
    turn_id?: string;
    [key: string]: any;
  }>;
  matched_precedent?: PrecedentSimilarityMatch | null;
  matching_factors?: string[];
  workflow_trace?: WorkflowTrace | null;
}

/**
 * Precedent Workflow Mining & Jev Similarity Types (POC v2 Extension)
 */
export interface WorkflowToolCall {
  tool_name: string;
  input_summary?: string | null;
  output_summary?: string | null;
  executed_at?: string | null;
  status: string;
}

export interface WorkflowHumanAction {
  actor_role: string;
  action_type: string;
  summary: string;
  timestamp?: string | null;
}

export interface WorkflowPolicyCitation {
  policy_code: string;
  clause: string;
  rationale: string;
  relevance_score: number;
}

export interface WorkflowDecision {
  verdict: string;
  penalty_amount: number;
  rationale: string;
  decided_by: string;
  decided_at: string;
}

export interface WorkflowTrace {
  agent_tools_called: WorkflowToolCall[];
  human_actions_performed: WorkflowHumanAction[];
  driver_response_summary: string;
  related_policies: WorkflowPolicyCitation[];
  final_decision?: WorkflowDecision | null;
  timeline?: WorkflowTimelineEvent[];
}

export interface WorkflowTimelineEvent {
  event_type: string;
  occurred_at: string;
  label?: string | null;
}

export interface PrecedentWorkflowItem {
  id: string;
  case_id?: string | null;
  violation_code: string;
  claim_type: string;
  district?: string | null;
  title: string;
  driver_statement_summary: string;
  workflow_trace: WorkflowTrace;
  verdict: string;
  confidence_score: number;
  created_at?: string | null;
}

export interface PrecedentSimilarityMatch {
  precedent_id: string;
  precedent_case_id?: string | null;
  title: string;
  similarity_score: number;
  matching_factors: string[];
  recommended_procedure: string[];
  precedent_verdict: string;
  confidence_rationale: string;
  model_used: string;
  precedent_workflow?: WorkflowTrace | null;
}

export interface PrecedentMatchRequest {
  case_id: string;
  claim_type?: string | null;
  driver_statement?: string | null;
  violation_code?: string | null;
  telemetry_summary?: Record<string, any> | null;
}

export interface PrecedentMatchResponse {
  case_id: string;
  has_match: boolean;
  top_match?: PrecedentSimilarityMatch | null;
  all_candidates: PrecedentSimilarityMatch[];
}

export interface DriverPastIncident {
  trip_id: string;
  occurred_at: string;
  violation_type: string;
  investigation_finding: string;
  action_taken: string;
  status: "penalized" | "exonerated" | "warned";
}

export interface DriverScorecardAnalysis {
  violation_ratio_90d: number; // percentage, e.g. 3.8
  fined_ratio: number; // percentage, e.g. 50.0
  repeat_offense_risk_score: number; // 0 - 100, e.g. 78
  benchmark_violation_ratio: number; // e.g. 5.0
  past_incidents: DriverPastIncident[];
  tenure_months: number;
  total_trips?: number;
  total_cases?: number;
}

export interface DriverScorecardResponse extends DriverScorecardAnalysis {
  driver_id: string;
}

export interface DriverVehicleInfo {
  model: string | null;
  plate: string | null;
}

export interface WeeklyRatingTrend {
  week_label: string;
  week_start: string;
  average_rating: number | null;
  rated_count: number;
}

export interface DriverProfileResponse {
  driver_id: string;
  display_name: string | null;
  vehicle: DriverVehicleInfo | null;
  member_since: string | null;
  scorecard: DriverScorecardResponse;
  rating_average: number | null;
  rated_count: number;
  distribution: Record<string, number>;
  weekly_trend: WeeklyRatingTrend[];
}

export interface DriverFeedbackItem {
  id: string;
  stars: number | null;
  comment: string | null;
  date: string | null;
  created_at?: string | null;
}

export interface DriverFeedbackResponse {
  items: DriverFeedbackItem[];
  next_cursor: string | null;
  total: number;
}

export interface TrafficProbeSummary {
  corridor_name: string;
  status: "NORMAL" | "SLOWER" | "CONGESTED";
  ambient_speed_kmh: number;
  osrm_baseline_speed_kmh: number;
  peer_vehicles_count: number;
  observation_radius_m: number;
  provider: string;
  congestion_level: "clear" | "moderate" | "heavy";
}

export interface HypothesisEvidence {
  stall_duration_s: number | null;
  davi_score: number | null;
  drift_distance_m: number | null;
  gap_anomaly: string;
  mock_location_detected: boolean;
  gps_accuracy_m: number | null;
  gps_state: string;
  ping_latency_ms: number | null;
  battery_level_pct: number | null;
  device_integrity: "verified" | "compromised" | "unknown";
  prior_warnings_count: number | null;
  policy_code: string;
  policy_status: string;
  violation_code: string;
  violation_title: string;
  violation_probability_pct: number;
  detection_reason: string;
}

export type AppRole = "fraud_analyst" | "analyst" | "driver" | "admin";

export interface UserAccountSettings {
  id: string;
  display_name: string;
  email?: string | null;
  roles: string[];
  primary_role: AppRole;
  organization_id: string;
  driver_id?: string | null;
}

export interface AccountUserItem {
  id: string;
  display_name: string;
  external_subject?: string | null;
  roles: string[];
  status: string;
}

export interface AnalystDecisionMetrics {
  today_decisions_count: number;
  thirty_day_decisions_count: number;
  average_mttr_seconds: number | null;
  model_agreement_pct: number | null;
  quality_overturn_pct: number | null;
}

export interface AnalystGovernanceLimits {
  dismiss_authority: string;
  warning_authority: string;
  direct_fine_limit_vnd: number;
  suspension_authority: string;
  role: string;
}

export interface ActiveReviewLeaseSummary {
  case_id: string;
  case_code: string;
  severity: string;
  driver_name?: string | null;
  vehicle_plate?: string | null;
  expires_at: string;
  remaining_seconds: number;
}

export interface AnalystAuditLedgerItem extends StagedAdjudicationContext {
  id: string;
  case_id: string;
  case_code: string;
  timestamp: string;
  actor_id: string;
  actor_name: string;
  actor_type: "analyst" | "system" | "driver";
  action: string;
  verdict: string;
  subject_entity: string;
  triggered_violation: string;
  sanction?: string | null;
  rationale: string;
  snapshot_version: number;
  request_hash?: string | null;
}

export interface AnalystAuditProfileResponse {
  analyst_id: string;
  display_name: string;
  roles: string[];
  organization_id: string;
  metrics: AnalystDecisionMetrics;
  governance_limits: AnalystGovernanceLimits;
  active_lease: ActiveReviewLeaseSummary | null;
  ledger: AnalystAuditLedgerItem[];
  total_ledger_count: number;
}

export interface AnalyticsQueueMetrics {
  total_cases: number;
  active_backlog: number;
  pending_driver_confirmation: number;
  claimed_cases: number;
  available_unclaimed: number;
  priority_distribution: Record<string, number>;
}

export interface AnalyticsDispositionMetrics {
  driver_confirmed_resolutions: number;
  analyst_adjudications_total: number;
  analyst_decisions_breakdown: Record<string, number>;
  auto_dismissed_count: number;
}

export interface AnalyticsPerformanceMetrics {
  average_mttr_seconds: number | null;
  hitl_enforcement_ratio_pct: number | null;
  reviewer_concordance_pct: number | null;
}

export interface AnalyticsSystemHealth {
  database_healthy: boolean;
  worker_status: string;
  environment: string;
}

export interface AnalyticsMetricsResponse {
  scope: string;
  organization_id: string;
  window_days: number | null;
  generated_at: string;
  queue: AnalyticsQueueMetrics;
  dispositions: AnalyticsDispositionMetrics;
  categories: Record<string, number>;
  performance: AnalyticsPerformanceMetrics;
  health: AnalyticsSystemHealth;
}

export * from "./driver-blocks";

