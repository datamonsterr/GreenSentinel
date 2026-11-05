import {
  AccountUserItem,
  AdjudicationOutcome,
  AdjudicationRequest,
  AdjudicationResponse,
  AgentSessionResponse,
  AnalystAuditProfileResponse,
  AnalyticsMetricsResponse,
  AnalystDelegateInquiryRequest,
  AppRole,
  CaseActionRequest,
  CaseActionResponse,
  CaseDetailResponse,
  CaseListResponse,
  CasePolicyResponse,
  CaseProgressEvent,
  ChatRequest,
  ChatResponse,
  ClaimCaseRequest,
  ClaimCaseResponse,
  DisputeDossierResponse,
  DriverCaseListResponse,
  DriverCaseSessionItem,
  DriverChatRequest,
  DriverChatResponse,
  DriverDisputeContextResponse,
  DriverFeedbackResponse,
  DriverProfileResponse,
  DriverScorecardResponse,
  DriverTripItem,
  DriverTripsResponse,
  DriverTripsSummaryResponse,
  ForensicBriefResponse,
  HealthResponse,
  ObservabilitySummary,
  PolicyChatRequest,
  PolicyCitationEvent,
  PrecedentMatchRequest,
  PrecedentMatchResponse,
  PrecedentWorkflowItem,
  ReleaseCaseRequest,
  ReleaseCaseResponse,
  SimulationTriggerRequest,
  SimulationTriggerResponse,
  UserAccountSettings,
  WorkflowTrace,
  PreliminaryJudgment,
} from "@/types/schemas";
import { consumeChatEventStream } from "@/lib/chat-event-stream";

export type ApiTokenProvider = (options?: { skipCache?: boolean; template?: string }) => Promise<string | null>;
let tokenProvider: ApiTokenProvider | null = null;

export function setApiTokenProvider(provider: ApiTokenProvider | null): void {
  tokenProvider = provider;
}

export function isJwtExpiredOrNearExpiry(token: string, thresholdSeconds: number = 10): boolean {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return false;
    const base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const jsonStr = typeof atob === "function" ? atob(base64) : Buffer.from(base64, "base64").toString("utf-8");
    const payload = JSON.parse(jsonStr);
    if (typeof payload.exp === "number") {
      const expiresAt = payload.exp * 1000;
      return expiresAt - Date.now() <= thresholdSeconds * 1000;
    }
  } catch {
    // If parsing fails, allow request to proceed and let server verify
  }
  return false;
}

export async function authorizedHeaders(headers: HeadersInit = {}, forceRefresh: boolean = false): Promise<Headers> {
  const result = new Headers(headers);
  if (tokenProvider) {
    let token = await tokenProvider(forceRefresh ? { skipCache: true } : undefined);
    if (token && !forceRefresh && isJwtExpiredOrNearExpiry(token)) {
      const fresh = await tokenProvider({ skipCache: true });
      if (fresh) token = fresh;
    }
    if (token) result.set("Authorization", `Bearer ${token}`);
  }
  return result;
}

export const getApiBaseUrl = (): string => {
  const envUrl = process.env.NEXT_PUBLIC_API_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "";

  // Filter out invalid masked tokens, placeholders, or malformed strings
  if (
    envUrl &&
    !envUrl.includes("[SENSITIVE]") &&
    !envUrl.includes("placeholder")
  ) {
    if (envUrl.startsWith("http://") || envUrl.startsWith("https://") || envUrl.startsWith("/")) {
      return envUrl.replace(/\/+$/, "");
    }
  }

  // Automatic domain-aware routing in browser.
  // IMPORTANT: check most-specific substrings first — dev/staging hostnames
  // also contain "p-063" so the generic production check must be last and
  // explicitly exclude dev/staging to avoid misrouting.
  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    const isLocal =
      host === "localhost" ||
      host === "127.0.0.1" ||
      host === "::1" ||
      host.startsWith("192.168.") ||
      host.startsWith("10.");
    const isDev =
      isLocal ||
      host.includes("p-063-dev") ||
      host.includes("dev.p-063") ||
      host.includes("dev-p-063") ||
      host.includes("p-063-driver") ||
      host.includes("v1.p-063") ||
      host.includes("v1-p-063") ||
      host.includes("p-063-v1");
    const isStaging =
      host.includes("staging.p-063") ||
      host.includes("staging-p-063") ||
      host.includes("p-063-staging");
    if (isLocal) return ""; // fall through to localhost:8000 at the bottom
    if (isDev) return "https://p063-backend-dev.up.railway.app";
    if (isStaging) return "https://p063-backend-staging.up.railway.app";
    if ((host.includes("p-063") || host.includes("p063")) && !isDev && !isStaging) {
      return "https://p063-backend-production.up.railway.app";
    }
    return "";
  }

  // The same-origin Next.js proxy is configured independently for every deployment.
  return typeof window !== "undefined"
    ? ""
    : (process.env.API_BASE_URL || "https://p063-backend-production.up.railway.app");
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(`API Error ${status}: ${message}`);
    this.name = "ApiError";
    this.status = status;
  }
}

export function parseErrorStatus(err: unknown): number | null {
  if (err && typeof err === "object" && "status" in err && typeof (err as any).status === "number") {
    return (err as any).status;
  }
  const msg = err instanceof Error ? err.message : String(err ?? "");
  const match = msg.match(/API Error (\d+)/) || msg.match(/\b(400|401|403|404|422|500|502|503|504)\b/);
  return match ? Number(match[1]) : null;
}

/**
 * Common JSON request helper with HTTP error parsing and 401 token refresh retry
 */
export const JSON_REQUEST_TIMEOUT_MS = 15_000;

export async function requestJson<T>(url: string, options?: RequestInit, timeoutMs?: number): Promise<T> {
  const controller = new AbortController();
  const externalSignal = options?.signal;
  let rejectCancellation!: (reason: unknown) => void;
  const cancellation = new Promise<never>((_, reject) => { rejectCancellation = reject; });
  const cancel = (reason: unknown) => {
    // Reject independently: token providers and some transports ignore abort.
    rejectCancellation(reason);
    controller.abort(reason);
  };
  const onExternalAbort = () => cancel(externalSignal?.reason ?? new DOMException("Request cancelled", "AbortError"));
  const timeout = timeoutMs === undefined ? undefined : setTimeout(() => cancel(new DOMException("Request timed out", "TimeoutError")), timeoutMs);
  externalSignal?.addEventListener("abort", onExternalAbort, { once: true });
  if (externalSignal?.aborted) onExternalAbort();

  const performRequest = async (): Promise<T> => {
    controller.signal.throwIfAborted();
    const headers = await authorizedHeaders({
      "Content-Type": "application/json",
      ...(options?.headers || {}),
    });
    // Do not send a late mutation after authentication exceeded its deadline.
    controller.signal.throwIfAborted();
    let response = await fetch(url, { ...options, signal: controller.signal, headers });
    controller.signal.throwIfAborted();

    if (response.status === 401 && tokenProvider) {
      const refreshedHeaders = await authorizedHeaders({
        "Content-Type": "application/json",
        ...(options?.headers || {}),
      }, true);
      controller.signal.throwIfAborted();
      response = await fetch(url, { ...options, signal: controller.signal, headers: refreshedHeaders });
      controller.signal.throwIfAborted();
    }

    if (!response.ok) {
      let errorDetail = response.statusText;
      try {
        const errBody = await response.json();
        if (errBody && typeof errBody === "object") {
          errorDetail = errBody.detail || errBody.message || JSON.stringify(errBody);
        }
      } catch {
        // Non-JSON errors retain the HTTP status text.
      }
      controller.signal.throwIfAborted();
      throw new ApiError(response.status, errorDetail);
    }
    const result = await response.json();
    controller.signal.throwIfAborted();
    return result as T;
  };

  try {
    return await Promise.race([cancellation, performRequest()]);
  } finally {
    clearTimeout(timeout);
    externalSignal?.removeEventListener("abort", onExternalAbort);
  }
}

/**
 * 1. Fetch case triage list
 * Supports both positional parameters and object options:
 * - fetchCases("OPEN", "P0", 50, 0)
 * - fetchCases({ status: "OPEN", priority: "P0", limit: 50, offset: 0 })
 */
export async function fetchCases(
  statusOrOptions?:
    | string
    | {
        status?: string;
        priority?: string;
        search?: string;
        limit?: number;
        offset?: number;
        availability?: "available" | "mine" | "all";
      },
  priority?: string,
  limit?: number,
  offset?: number
): Promise<CaseListResponse> {
  const baseUrl = getApiBaseUrl();
  const params = new URLSearchParams();

  if (statusOrOptions && typeof statusOrOptions === "object") {
    if (statusOrOptions.availability) params.append("availability", statusOrOptions.availability);
    if (statusOrOptions.status) params.append("status", statusOrOptions.status);
    if (statusOrOptions.priority) params.append("priority", statusOrOptions.priority);
    if (statusOrOptions.search && statusOrOptions.search.trim()) {
      params.append("search", statusOrOptions.search.trim());
    }
    if (statusOrOptions.limit !== undefined) params.append("limit", String(statusOrOptions.limit));
    if (statusOrOptions.offset !== undefined) params.append("offset", String(statusOrOptions.offset));
  } else {
    if (statusOrOptions) params.append("status", statusOrOptions);
    if (priority) params.append("priority", priority);
    if (limit !== undefined) params.append("limit", String(limit));
    if (offset !== undefined) params.append("offset", String(offset));
  }

  const queryString = params.toString();
  const url = `${baseUrl}/api/v1/cases${queryString ? `?${queryString}` : ""}`;
  return requestJson<CaseListResponse>(url, { method: "GET" });
}

export interface FetchCaseHistoryOptions {
  status?: string;
  search?: string;
  decision?: string;
  analyst_id?: string;
  start_date?: string;
  end_date?: string;
  limit?: number;
  offset?: number;
}

/**
 * 1.1 Fetch processed case history
 */
export async function fetchCaseHistory(
  options?: FetchCaseHistoryOptions
): Promise<CaseListResponse> {
  const baseUrl = getApiBaseUrl();
  const params = new URLSearchParams();

  if (options) {
    if (options.status) params.append("status", options.status);
    if (options.search && options.search.trim()) params.append("search", options.search.trim());
    if (options.decision) params.append("decision", options.decision);
    if (options.analyst_id) params.append("analyst_id", options.analyst_id);
    if (options.start_date) params.append("start_date", options.start_date);
    if (options.end_date) params.append("end_date", options.end_date);
    if (options.limit !== undefined) params.append("limit", String(options.limit));
    if (options.offset !== undefined) params.append("offset", String(options.offset));
  }

  const queryString = params.toString();
  const url = `${baseUrl}/api/v1/cases/history${queryString ? `?${queryString}` : ""}`;
  return requestJson<CaseListResponse>(url, { method: "GET" });
}

/**
 * 2. Fetch full case detail by ID
 */
export async function fetchCaseDetail(id: string): Promise<CaseDetailResponse> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/cases/${encodeURIComponent(id)}`;
  return requestJson<CaseDetailResponse>(url, { method: "GET" });
}

/**
 * 2.1 Fetch objective Forensic Brief of observed abnormalities for a case
 */
export async function fetchForensicBrief(id: string): Promise<ForensicBriefResponse> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/cases/${encodeURIComponent(id)}/forensic-brief`;
  return requestJson<ForensicBriefResponse>(url, { method: "GET" });
}

/**
 * 2.2 Fetch case-specific policy version, action matrix, and regulation clauses
 */
export async function fetchCasePolicy(id: string, query?: string): Promise<CasePolicyResponse> {
  const baseUrl = getApiBaseUrl();
  const params = new URLSearchParams();
  if (query) params.append("query", query);
  const qs = params.toString();
  const url = `${baseUrl}/api/v1/cases/${encodeURIComponent(id)}/policy${qs ? `?${qs}` : ""}`;
  return requestJson<CasePolicyResponse>(url, { method: "GET" });
}

/**
 * 2.3 Fetch live 90-day driver scorecard (replaces hash mock, issue #100)
 */
export async function fetchDriverScorecard(
  driverId: string
): Promise<DriverScorecardResponse> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/drivers/${encodeURIComponent(driverId)}/scorecard`;
  return requestJson<DriverScorecardResponse>(url, { method: "GET" });
}

/**
 * 2.4 Fetch live driver scorecard via the case alias route
 */
export async function fetchCaseDriverScorecard(
  caseId: string
): Promise<DriverScorecardResponse> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/cases/${encodeURIComponent(caseId)}/driver-scorecard`;
  return requestJson<DriverScorecardResponse>(url, { method: "GET" });
}

/**
 * 3. Claim a review lease for a case
 * Supports positional (id, analyst_id, lease_duration_seconds) or object payload
 */
export async function claimCase(
  id: string,
  analystIdOrPayload: string | ClaimCaseRequest,
  leaseDurationSeconds: number = 300
): Promise<ClaimCaseResponse> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/cases/${encodeURIComponent(id)}/claim`;

  const body: ClaimCaseRequest =
    typeof analystIdOrPayload === "string"
      ? { analyst_id: analystIdOrPayload, lease_duration_seconds: leaseDurationSeconds }
      : analystIdOrPayload;

  return requestJson<ClaimCaseResponse>(url, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/**
 * 3.1 Release a review lease for a case
 */
export async function releaseCase(
  id: string,
  analystIdOrPayload: string | ReleaseCaseRequest,
  role?: string,
  force?: boolean
): Promise<ReleaseCaseResponse> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/cases/${encodeURIComponent(id)}/release`;

  const body: ReleaseCaseRequest =
    typeof analystIdOrPayload === "string"
      ? { analyst_id: analystIdOrPayload, role, force }
      : analystIdOrPayload;

  return requestJson<ReleaseCaseResponse>(url, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/**
 * 4. Record action on a case (REQUEST_EVIDENCE, ESCALATE, DEFER)
 */
export async function recordCaseAction(
  id: string,
  actionPayload: CaseActionRequest
): Promise<CaseActionResponse> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/cases/${encodeURIComponent(id)}/actions`;
  return requestJson<CaseActionResponse>(url, {
    method: "POST",
    body: JSON.stringify(actionPayload),
  }, JSON_REQUEST_TIMEOUT_MS);
}

/**
 * 5. Adjudicate case (AGREE, DISAGREE)
 */
export async function adjudicateCase(
  id: string,
  adjudicationPayload: AdjudicationRequest
): Promise<AdjudicationResponse> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/cases/${encodeURIComponent(id)}/adjudicate`;
  return requestJson<AdjudicationResponse>(url, {
    method: "POST",
    body: JSON.stringify(adjudicationPayload),
  }, JSON_REQUEST_TIMEOUT_MS);
}

export async function recordPreliminaryJudgment(
  id: string,
  payload: { analyst_id: string; judgment: string; note?: string | null },
): Promise<PreliminaryJudgment> {
  const baseUrl = getApiBaseUrl();
  return requestJson<PreliminaryJudgment>(`${baseUrl}/api/v1/cases/${encodeURIComponent(id)}/preliminary-assessment`, {
    method: "POST", body: JSON.stringify(payload),
  });
}

/**
 * Helper to parse SSE streams over ReadableStream
 */
async function consumeSseStream(
  response: Response,
  onEvent: (event: string, data: string) => void,
  onError?: (err: unknown) => void
): Promise<void> {
  if (!response.body) {
    throw new Error("Response body is not readable");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split(/\r?\n\r?\n/);
      buffer = parts.pop() ?? "";

      for (const part of parts) {
        if (!part.trim()) continue;
        let eventType = "message";
        let data = "";
        const lines = part.split(/\r?\n/);
        for (const line of lines) {
          if (line.startsWith("event:")) {
            eventType = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            const dataSlice = line.slice(5).trim();
            data = data ? `${data}\n${dataSlice}` : dataSlice;
          }
        }
        if (data) {
          onEvent(eventType, data);
        }
      }
    }

    if (buffer.trim()) {
      let eventType = "message";
      let data = "";
      const lines = buffer.split(/\r?\n/);
      for (const line of lines) {
        if (line.startsWith("event:")) {
          eventType = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          const dataSlice = line.slice(5).trim();
          data = data ? `${data}\n${dataSlice}` : dataSlice;
        }
      }
      if (data) {
        onEvent(eventType, data);
      }
    }
  } catch (err: any) {
    if (err.name === "AbortError") {
      return; // Graceful abort
    }
    if (onError) {
      onError(err);
    } else {
      throw err;
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * 6. Stream real-time case progress events via SSE
 * Returns an abort function to cancel stream.
 */
export function streamCaseProgress(
  id: string,
  onData: (data: CaseProgressEvent) => void,
  onError?: (err: unknown) => void
): () => void {
  const controller = new AbortController();
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/cases/${encodeURIComponent(id)}/stream`;

  const fetchStream = async (forceRefresh: boolean = false): Promise<Response> => {
    const headers = await authorizedHeaders({ Accept: "text/event-stream" }, forceRefresh);
    return fetch(url, {
      method: "GET",
      headers,
      signal: controller.signal,
    });
  };

  (async () => {
    try {
      let res = await fetchStream(false);
      if (res.status === 401 && tokenProvider) {
        res = await fetchStream(true);
      }
      if (!res.ok) {
        throw new Error(`SSE Connection failed with status ${res.status}`);
      }
      await consumeSseStream(
        res,
        (event, data) => {
          try {
            const parsed = JSON.parse(data);
            onData(parsed as CaseProgressEvent);
          } catch (e) {
            onError?.(e);
          }
        },
        onError
      );
    } catch (err: any) {
      if (err.name === "AbortError") return;
      onError?.(err);
    }
  })();

  return () => controller.abort();
}

/**
 * Alias for streamCaseProgress matching subscribeCaseStream naming convention
 */
export const subscribeCaseStream = streamCaseProgress;

/**
 * 7. Stream policy copilot chat responses & citations
 * Returns an abort function to cancel stream.
 */
export function streamPolicyChat(
  payload: PolicyChatRequest,
  onDelta: (delta: string) => void,
  onCitation?: (citation: PolicyCitationEvent) => void,
  onDone?: () => void,
  onError?: (err: unknown) => void,
  onToolCall?: (toolCall: { tool: string; status: string }) => void,
  onThinking?: (thinking: { status?: string; label?: string }) => void,
  onToolDone?: (tool: { tool?: string; status?: string }) => void
): () => void {
  const controller = new AbortController();
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/policy/chat/stream`;

  const fetchStream = async (forceRefresh: boolean = false): Promise<Response> => {
    const headers = await authorizedHeaders(
      { "Content-Type": "application/json", Accept: "text/event-stream" },
      forceRefresh
    );
    return fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
  };

  (async () => {
    try {
      let res = await fetchStream(false);
      if (res.status === 401 && tokenProvider) {
        // Expired Clerk session: refresh token with skipCache and retry once
        res = await fetchStream(true);
      }
      if (!res.ok) {
        throw new Error(`Policy Chat stream failed with status ${res.status}`);
      }
      if (!res.body) {
        throw new Error("Empty SSE stream");
      }
      await consumeChatEventStream(res.body, {
        signal: controller.signal,
        onDelta: (delta) => {
          onDelta(delta);
        },
        onCitation: (citation) => {
          onCitation?.(citation as PolicyCitationEvent);
        },
        onThinking: (label) => {
          onThinking?.({ status: "running", label });
        },
        onToolStart: (tool) => {
          onToolCall?.({ tool: tool.tool_name, status: tool.status === "failed" ? "blocked" : "running" });
        },
        onToolEnd: (tool) => {
          onToolDone?.({ tool: tool.tool_name, status: tool.status === "succeeded" ? "success" : "error" });
        },
        onTerminal: (state) => {
          if (state.status === "completed") {
            onDone?.();
          } else if (state.status === "error" || state.status === "interrupted") {
            onError?.(new Error(state.error?.message || "Agent request failed"));
          }
        },
        onError: (err) => {
          onError?.(err);
        },
      });
    } catch (err: any) {
      if (err.name === "AbortError" || controller.signal.aborted) return;
      onError?.(err);
    }
  })();

  return () => controller.abort();
}

export function fetchAgentSession(caseId: string): Promise<AgentSessionResponse> {
  return requestJson<AgentSessionResponse>(`${getApiBaseUrl()}/api/v1/cases/${encodeURIComponent(caseId)}/agent-session`, { method: "GET" });
}

/**
 * 8. Trigger fraud simulation scenario
 */
export async function triggerSimulation(
  scenario: string,
  analystIdOrPayload?: string | SimulationTriggerRequest,
  seed?: number
): Promise<SimulationTriggerResponse> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/simulations/${encodeURIComponent(scenario)}`;

  let body: SimulationTriggerRequest | undefined;
  if (typeof analystIdOrPayload === "string") {
    body = { analyst_id: analystIdOrPayload, seed };
  } else if (analystIdOrPayload) {
    body = analystIdOrPayload;
  }

  return requestJson<SimulationTriggerResponse>(url, {
    method: "POST",
    body: body ? JSON.stringify(body) : undefined,
  });
}

/**
 * 9. Legacy / LangGraph Agent Chat
 */
export async function chatWithAgent(message: string): Promise<ChatResponse> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/chat`;
  const body: ChatRequest = { message };
  return requestJson<ChatResponse>(url, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/**
 * 10. Check backend health
 */
export async function getApiHealth(): Promise<HealthResponse> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/health`;
  return requestJson<HealthResponse>(url, { method: "GET" });
}

export async function fetchCurrentAnalyst(): Promise<{id:string;name:string;role:string;organization_id?:string}> {
  const principal = await requestJson<{id:string;display_name:string;roles:string[];organization_id?:string}>(`${getApiBaseUrl()}/api/v1/me`, {method:"GET"});
  return {id:principal.id,name:principal.display_name,role:principal.roles[0] || "analyst",organization_id:principal.organization_id};
}

export async function fetchObservabilitySummary(): Promise<ObservabilitySummary> {
  return requestJson<ObservabilitySummary>(`${getApiBaseUrl()}/api/v1/observability/summary`, {method:"GET"});
}

/**
 * 10.0 Fetch driver profile with identity, vehicle, scorecard, ratings, and trend
 */
export async function fetchDriverProfile(driverId?: string): Promise<DriverProfileResponse> {
  const baseUrl = getApiBaseUrl();
  const headers: Record<string, string> = {};
  if (driverId) headers["x-driver-id"] = driverId;
  return requestJson<DriverProfileResponse>(`${baseUrl}/api/v1/driver/profile`, { method: "GET", headers });
}

/**
 * 10.0b Fetch paginated customer feedback for the driver
 */
export async function fetchDriverFeedback(
  cursor?: string,
  limit: number = 20,
  driverId?: string
): Promise<DriverFeedbackResponse> {
  const baseUrl = getApiBaseUrl();
  const params = new URLSearchParams();
  if (cursor) params.append("cursor", cursor);
  if (limit) params.append("limit", limit.toString());
  const qs = params.toString();
  const url = `${baseUrl}/api/v1/driver/feedback${qs ? `?${qs}` : ""}`;
  const headers: Record<string, string> = {};
  if (driverId) headers["x-driver-id"] = driverId;
  return requestJson<DriverFeedbackResponse>(url, { method: "GET", headers });
}

/**
 * 10.1 Fetch driver case dispute sessions
 */
export async function fetchDriverCases(driverId?: string): Promise<DriverCaseListResponse> {
  const baseUrl = getApiBaseUrl();
  const headers: Record<string, string> = {};
  if (driverId) headers["x-driver-id"] = driverId;
  return requestJson<DriverCaseListResponse>(`${baseUrl}/api/v1/driver/cases`, { method: "GET", headers });
}

/**
 * 10.2 Fetch driver session messages
 */
export async function fetchDriverSession(caseId: string, driverId?: string): Promise<AgentSessionResponse> {
  const baseUrl = getApiBaseUrl();
  const headers: Record<string, string> = {};
  if (driverId) headers["x-driver-id"] = driverId;
  return requestJson<AgentSessionResponse>(`${baseUrl}/api/v1/driver/cases/${encodeURIComponent(caseId)}/session`, { method: "GET", headers });
}

/**
 * 10.3 Fetch driver trips history (cursor paginated, status/month filtered)
 */
export async function fetchDriverTrips(options?: {
  cursor?: string;
  status?: string;
  month?: string;
  limit?: number;
  signal?: AbortSignal;
}): Promise<DriverTripsResponse> {
  const baseUrl = getApiBaseUrl();
  const params = new URLSearchParams();
  if (options?.cursor) params.append("cursor", options.cursor);
  if (options?.status) params.append("status", options.status);
  if (options?.month) params.append("month", options.month);
  if (options?.limit) params.append("limit", String(options.limit));
  const qs = params.toString();
  const url = `${baseUrl}/api/v1/driver/trips${qs ? `?${qs}` : ""}`;
  return requestJson<DriverTripsResponse>(url, { method: "GET", signal: options?.signal });
}

/**
 * 10.4 Fetch driver trips monthly summary
 */
export async function fetchDriverTripsSummary(options?: {
  month?: string;
  signal?: AbortSignal;
}): Promise<DriverTripsSummaryResponse> {
  const baseUrl = getApiBaseUrl();
  const params = new URLSearchParams();
  if (options?.month) params.append("month", options.month);
  const qs = params.toString();
  const url = `${baseUrl}/api/v1/driver/trips/summary${qs ? `?${qs}` : ""}`;
  return requestJson<DriverTripsSummaryResponse>(url, { method: "GET", signal: options?.signal });
}

/**
 * 11. Fetch driver dispute context for a case
 */
export async function getDriverDisputeContext(
  caseId: string,
  driverId?: string
): Promise<DriverDisputeContextResponse> {
  const baseUrl = getApiBaseUrl();
  const params = new URLSearchParams();
  if (driverId) params.append("driver_id", driverId);
  const qs = params.toString();
  const url = `${baseUrl}/api/v1/driver/cases/${encodeURIComponent(caseId)}/dispute${qs ? `?${qs}` : ""}`;
  const headers: Record<string, string> = {};
  if (driverId) headers["x-driver-id"] = driverId;
  return requestJson<DriverDisputeContextResponse>(url, { method: "GET", headers });
}

/**
 * 12. Submit driver statement and evaluate autonomous exoneration or escalation
 */
export async function sendDriverChat(
  caseId: string,
  req: DriverChatRequest
): Promise<DriverChatResponse> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/driver/cases/${encodeURIComponent(caseId)}/chat`;
  const headers: Record<string, string> = {};
  if (req.driver_id) headers["x-driver-id"] = req.driver_id;
  return requestJson<DriverChatResponse>(url, {
    method: "POST",
    headers,
    body: JSON.stringify({ ...req, case_id: caseId }),
  });
}

/**
 * 12.1 Issue a single-use confirmation token for accept/reject actions (Issue #483)
 */
export async function requestDriverConfirmation(
  caseId: string,
  action: "acknowledge" | "submit_statement",
  draftHash: string = ""
): Promise<{ confirmation_token: string }> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/driver/cases/${encodeURIComponent(caseId)}/confirmations`;
  return requestJson<{ confirmation_token: string }>(url, {
    method: "POST",
    body: JSON.stringify({ action, draft_hash: draftHash }),
  });
}

/**
 * 12.2 Submit driver violation acknowledgment gated by confirmation token (Issue #483)
 */
export async function submitDriverAcknowledge(
  caseId: string,
  token: string
): Promise<Record<string, unknown>> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/driver/cases/${encodeURIComponent(caseId)}/acknowledge`;
  return requestJson<Record<string, unknown>>(url, {
    method: "POST",
    body: JSON.stringify({ confirmation_token: token }),
  });
}

/**
 * 12.3 Submit driver dispute statement gated by confirmation token (Issue #483)
 */
export async function submitDriverStatement(
  caseId: string,
  token: string,
  reasonSummary: string,
  evidence: Array<Record<string, unknown>> = []
): Promise<Record<string, unknown>> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/driver/cases/${encodeURIComponent(caseId)}/statement`;
  return requestJson<Record<string, unknown>>(url, {
    method: "POST",
    body: JSON.stringify({
      confirmation_token: token,
      reason_summary: reasonSummary,
      evidence,
    }),
  });
}

/**
 * 12.4 Save driver statement draft (Issue #483)
 */
export async function saveDriverDraft(
  caseId: string,
  draft: Record<string, unknown>
): Promise<Record<string, unknown>> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/driver/cases/${encodeURIComponent(caseId)}/statement-draft`;
  return requestJson<Record<string, unknown>>(url, {
    method: "PUT",
    body: JSON.stringify(draft),
  });
}

/**
 * 12.5 Fetch saved driver statement draft (Issue #483)
 */
export async function fetchDriverDraft(
  caseId: string
): Promise<Record<string, unknown> | null> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/driver/cases/${encodeURIComponent(caseId)}/statement-draft`;
  return requestJson<Record<string, unknown> | null>(url, { method: "GET" });
}

/**
 * 13. Stream driver dispute reply token-by-token followed by completion event
 */
export async function streamDriverChat(
  caseId: string,
  message: string,
  claimType?: string,
  onToken?: (token: string) => void,
  turnId?: string,
  eventSchemaVersion?: "1.0" | "1.1"
): Promise<DriverChatResponse> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/driver/cases/${encodeURIComponent(caseId)}/chat/stream`;

  const fetchStream = async (forceRefresh: boolean = false): Promise<Response> => {
    const headers = await authorizedHeaders(
      { "Content-Type": "application/json", Accept: "text/event-stream" },
      forceRefresh
    );
    const body: Record<string, any> = {
      case_id: caseId,
      message,
      claim_type: claimType,
    };
    if (turnId) body.turn_id = turnId;
    if (eventSchemaVersion) body.event_schema_version = eventSchemaVersion;
    return fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
  };

  let res = await fetchStream(false);
  if (res.status === 401 && tokenProvider) {
    res = await fetchStream(true);
  }
  if (!res.ok) {
    let errorDetail = res.statusText;
    try {
      const errBody = await res.json();
      if (errBody && typeof errBody === "object") {
        errorDetail = errBody.detail || errBody.message || JSON.stringify(errBody);
      }
    } catch {
      // Ignored if response is not json
    }
    throw new Error(`API Error ${res.status}: ${errorDetail}`);
  }

  let finalResponse: DriverChatResponse | null = null;
  let accumulatedReply = "";

  await consumeSseStream(res, (event, rawData) => {
    try {
      const parsed = JSON.parse(rawData);
      if (event === "token" || event === "delta" || (parsed && parsed.type === "text.delta")) {
        const token = parsed.token ?? parsed.delta ?? parsed.payload?.delta ?? "";
        accumulatedReply += token;
        onToken?.(token);
      } else if (event === "done" || event === "completion") {
        finalResponse = {
          case_id: parsed.case_id || caseId,
          driver_id: parsed.driver_id || "",
          reply: parsed.reply || accumulatedReply,
          dispute_status: parsed.dispute_status || "in_dispute",
          is_auto_dismissed: Boolean(parsed.is_auto_dismissed),
          exoneration_receipt: parsed.exoneration_receipt || null,
          needs_analyst_review: Boolean(parsed.needs_analyst_review),
        };
      } else if (parsed && parsed.type === "run.completed") {
        finalResponse = {
          case_id: parsed.case_id || caseId,
          driver_id: parsed.identity?.driver_id || parsed.driver_id || "",
          reply: accumulatedReply,
          dispute_status: "in_dispute",
          is_auto_dismissed: false,
          exoneration_receipt: null,
          needs_analyst_review: true,
        };
      }
    } catch {
      if (event === "token" || event === "delta") {
        accumulatedReply += rawData;
        onToken?.(rawData);
      }
    }
  });

  if (!finalResponse) {
    finalResponse = {
      case_id: caseId,
      driver_id: "",
      reply: accumulatedReply,
      dispute_status: "in_dispute",
      is_auto_dismissed: false,
      exoneration_receipt: null,
      needs_analyst_review: true,
    };
  }

  return finalResponse;
}

/**
 * 14. Delegate analyst inquiry to driver agent
 */
export async function delegateAnalystInquiry(
  caseId: string,
  req: AnalystDelegateInquiryRequest
): Promise<{ status: string; case_id: string }> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/cases/${encodeURIComponent(caseId)}/delegate-inquiry`;
  return requestJson<{ status: string; case_id: string }>(url, {
    method: "POST",
    body: JSON.stringify({ ...req, case_id: caseId }),
  });
}

/**
 * 15. Retrieve dispute dossier for HITL review
 */
export async function getDisputeDossier(
  caseId: string
): Promise<DisputeDossierResponse> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/cases/${encodeURIComponent(caseId)}/dispute-dossier`;
  return requestJson<DisputeDossierResponse>(url, { method: "GET" });
}

/**
 * 16. Retrieve synthesized workflow trace for a case
 */
export async function getCaseWorkflowTrace(
  caseId: string
): Promise<WorkflowTrace> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/cases/${encodeURIComponent(caseId)}/workflow-trace`;
  return requestJson<WorkflowTrace>(url, { method: "GET" });
}

export async function saveCaseWorkflowDraft(caseId: string, text: string, expectedVersion?: number) {
  const baseUrl = getApiBaseUrl();
  return requestJson<{ text: string; version: number; updated_at?: string | null; updated_by?: string | null }>(
    `${baseUrl}/api/v1/cases/${encodeURIComponent(caseId)}/workflow-draft`,
    { method: "PUT", body: JSON.stringify({ text, ...(expectedVersion == null ? {} : { expected_version: expectedVersion }) }) },
  );
}

/**
 * 17. Evaluate precedent similarity for a case
 */
export async function matchCasePrecedent(
  caseId: string,
  req: PrecedentMatchRequest
): Promise<PrecedentMatchResponse> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/cases/${encodeURIComponent(caseId)}/match-precedent`;
  return requestJson<PrecedentMatchResponse>(url, {
    method: "POST",
    body: JSON.stringify(req),
  });
}

/**
 * 18. List historical precedent workflows from Precedent Bank
 */
export async function listPrecedents(
  violationCode?: string,
  claimType?: string,
  limit: number = 50
): Promise<PrecedentWorkflowItem[]> {
  const baseUrl = getApiBaseUrl();
  const params = new URLSearchParams();
  if (violationCode) params.append("violation_code", violationCode);
  if (claimType) params.append("claim_type", claimType);
  if (limit) params.append("limit", String(limit));
  const qs = params.toString() ? `?${params.toString()}` : "";
  const url = `${baseUrl}/api/v1/precedents${qs}`;
  return requestJson<PrecedentWorkflowItem[]>(url, { method: "GET" });
}

/**
 * 19. Retrieve a single precedent workflow
 */
export async function getPrecedent(
  precedentId: string
): Promise<PrecedentWorkflowItem> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/precedents/${encodeURIComponent(precedentId)}`;
  return requestJson<PrecedentWorkflowItem>(url, { method: "GET" });
}

/**
 * 20. Apply precedent procedure to pre-fill case adjudication
 */
export async function applyPrecedentProcedure(
  caseId: string,
  precedentId: string
): Promise<{
  case_id: string;
  precedent_id: string;
  precedent_title: string;
  recommended_verdict: string;
  recommended_penalty_amount: number;
  recommended_rationale: string;
  policy_citations: Array<Record<string, any>>;
  recommended_tools: string[];
  applied_at: string;
}> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/cases/${encodeURIComponent(caseId)}/apply-precedent`;
  return requestJson<any>(url, {
    method: "POST",
    body: JSON.stringify({ precedent_id: precedentId }),
  });
}

/**
 * 21. Account Settings & Role Management
 */
export async function fetchAccountSettings(): Promise<UserAccountSettings> {
  const baseUrl = getApiBaseUrl();
  return requestJson<UserAccountSettings>(`${baseUrl}/api/v1/account/settings`, { method: "GET" });
}

export async function updateAccountSettings(data: { display_name: string }): Promise<UserAccountSettings> {
  const baseUrl = getApiBaseUrl();
  return requestJson<UserAccountSettings>(`${baseUrl}/api/v1/account/settings`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export async function fetchAccountUsers(): Promise<AccountUserItem[]> {
  const baseUrl = getApiBaseUrl();
  return requestJson<AccountUserItem[]>(`${baseUrl}/api/v1/account/users`, { method: "GET" });
}

export async function updateAccountUserRole(userId: string, role: AppRole): Promise<AccountUserItem> {
  const baseUrl = getApiBaseUrl();
  return requestJson<AccountUserItem>(`${baseUrl}/api/v1/account/users/${encodeURIComponent(userId)}/role`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  });
}

/**
  * 22. Analyst Profile, Decision Metrics & Immutable Activity Ledger
  */
export interface FetchAnalystAuditOptions {
  search?: string;
  verdict?: string;
  fromDate?: string;
  toDate?: string;
  limit?: number;
  offset?: number;
}

export async function fetchAnalystAuditProfile(
  options: FetchAnalystAuditOptions = {}
): Promise<AnalystAuditProfileResponse> {
  const baseUrl = getApiBaseUrl();
  const params = new URLSearchParams();
  if (options.search) params.set("search", options.search);
  if (options.verdict) params.set("verdict", options.verdict);
  if (options.fromDate) params.set("from_date", options.fromDate);
  if (options.toDate) params.set("to_date", options.toDate);
  if (typeof options.limit === "number") params.set("limit", String(options.limit));
  if (typeof options.offset === "number") params.set("offset", String(options.offset));

  const query = params.toString();
  const url = `${baseUrl}/api/v1/analyst/audit${query ? `?${query}` : ""}`;
  return requestJson<AnalystAuditProfileResponse>(url, { method: "GET" });
}

/**
 * 23. System & Operations Analytics
 */
export async function fetchAnalyticsMetrics(
  windowDays?: number
): Promise<AnalyticsMetricsResponse> {
  const baseUrl = getApiBaseUrl();
  const params = new URLSearchParams();
  if (windowDays !== undefined) params.append("window_days", String(windowDays));
  const qs = params.toString() ? `?${params.toString()}` : "";
  const url = `${baseUrl}/api/v1/analytics/metrics${qs}`;
  return requestJson<AnalyticsMetricsResponse>(url, { method: "GET" });
}
