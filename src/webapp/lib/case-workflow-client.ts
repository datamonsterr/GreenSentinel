import { getApiBaseUrl, requestJson } from "@/lib/api-client";

export type WorkflowStep = {
  key: string; label: string; actor_role: string; state: "done" | "current" | "pending";
  completed_at: string | null; actor_name?: string | null;
};
export type CaseWorkflow = {
  status: string; closed: boolean; steps: WorkflowStep[];
  next: { actor_role: string; text: string } | null; actions?: string[];
};

export async function fetchCaseWorkflow(id: string): Promise<CaseWorkflow> {
  return requestJson<CaseWorkflow>(`${getApiBaseUrl()}/api/v1/cases/${encodeURIComponent(id)}/workflow`, { method: "GET" });
}

export async function advanceCaseWorkflow(id: string, action: string): Promise<CaseWorkflow> {
  return requestJson<CaseWorkflow>(
    `${getApiBaseUrl()}/api/v1/cases/${encodeURIComponent(id)}/workflow/${encodeURIComponent(action)}`, { method: "POST" });
}
