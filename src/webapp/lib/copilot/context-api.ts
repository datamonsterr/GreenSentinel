/**
 * REST API Client for Case Agent Context (Issue #443).
 *
 * GET    /api/v1/cases/{id}/agent-context
 * DELETE /api/v1/cases/{id}/agent-context
 */

import { getApiBaseUrl, requestJson } from "@/lib/api-client";

export interface AgentContextUsageBreakdown {
  system: number;
  dossier: number;
  history: number;
  tool_results: number;
  query: number;
}

export interface AgentContextResponse {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  context_window: number;
  breakdown: AgentContextUsageBreakdown;
  turn_count: number;
}

export interface ClearAgentContextResponse {
  deleted_turns: number;
  deleted_messages: number;
}

/**
 * Retrieve agent context usage metrics and turn estimate for a given case.
 */
export async function getAgentContext(caseId: string): Promise<AgentContextResponse> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/cases/${encodeURIComponent(caseId)}/agent-context`;
  return requestJson<AgentContextResponse>(url, { method: "GET" });
}

/**
 * Hard-delete caller's agent runtime turns and messages for a given case.
 */
export async function clearAgentContext(caseId: string): Promise<ClearAgentContextResponse> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/cases/${encodeURIComponent(caseId)}/agent-context`;
  return requestJson<ClearAgentContextResponse>(url, { method: "DELETE" });
}
