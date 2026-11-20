import { getApiBaseUrl, requestJson } from "@/lib/api-client";

export type KbType = "parameter" | "motive" | "behavior" | "scenario" | "workflow";
export type KbStatus = "draft" | "ready_for_test" | "trial" | "published" | "retired";

export type ReplayReport = {
  cases_total: number; matched: number; changed_scenario: number; not_computable: number; est_turns: number;
  computable_ratio: number; gate_passed: boolean; gate_min: number; run_at: string;
};
export type HistoryEntry = { at: string; by: string | null; by_name: string | null; action: string; note: string };
export type KbObject = {
  id: string; type: KbType; code: string; version: number; status: KbStatus; name: string;
  scope: Record<string, string>; body: Record<string, unknown>; change_reason: string | null;
  author_id: string | null; author_name: string | null; approver_id: string | null; approver_name: string | null;
  replay: ReplayReport | null; override_reason: string | null; retired_reason: string | null;
  history: HistoryEntry[]; created_at: string; updated_at: string; published_at: string | null;
};
export type FormulaIssue = { code: string; message: string; position?: number; path?: string };
export type FormulaCheck = { ok: boolean; errors: FormulaIssue[]; warnings: FormulaIssue[]; used_params: string[]; sample: number | boolean | null };
export type CatalogueParam = {
  code: string; name: string; description: string; unit: string; source: string; owner: string; latency: string;
  sample: number; kind: "case" | "policy";
};
export type PreviewRow = {
  case_id: string; value: number | boolean | null; matched: boolean; error: FormulaIssue | null;
  params_used: Record<string, number>; assumed: string[];
};
export type PolicyDocument = {
  id: string; name: string; code: string; effective_from: string | null; effective_to: string | null; region: string | null;
  service: string | null; contract_type: string | null; filename: string | null; size_bytes: number;
  indexing_status: "not_indexed" | "indexed" | "embeddings_not_configured"; uploaded_by_name: string | null;
  created_at: string; has_text: boolean; used_by: { vi: string; en: string }[];
  analysis_status?: "pending" | "running" | "done" | "failed"; analysis_error?: string | null;
  analysis_counts?: Partial<Record<"chunks" | "candidates" | "proposals" | "reuse" | "extend" | "new" | "rejected_citation" | "rejected_schema" | "duplicates", number>>;
  analyzed_at?: string | null;
};
export type Proposal = {
  id: string; source: string; type: KbType; title: string; payload: Record<string, unknown>; source_excerpt: string | null;
  source_ref: string | null; mapping: "reuse" | "extend" | "new"; similarity: number | null; matched_code: string | null;
  status: "pending" | "accepted" | "edited" | "rejected"; reason_code: string | null; note: string | null;
  created_by: string | null; created_at: string; resulting_object_id: string | null;
};
export type AgentInfo = {
  id: string; name: { vi: string; en: string }; instruction_version: string; model: string; enabled: boolean | null;
  knowledge_types: KbType[]; knowledge_published: Record<string, number>; tools: string[]; memory_layers: string[];
  uses_policy_documents: boolean; reads: string; status?: string;
};
export type Registry = { agents: AgentInfo[]; published_counts: Record<string, number>; tool_catalogue: string[] };
export type ConfigItem = {
  key: string; type: "int" | "float" | "bool"; default: number | boolean; min: number | null; max: number | null;
  owner: "VH" | "KSGL" | "LEAD"; group: string; label: { vi: string; en: string }; scope: string;
  value: number | boolean; is_default: boolean; updated_at: string | null; can_edit: boolean;
};
export type ConfigResponse = {
  items: ConfigItem[];
  metrics: { window_days: number; avg_turns: number | null; pct_exhausted: number | null; pct_help: number | null; available: boolean };
};
export type ConfigHistory = {
  id: string; key: string; scope: string; old_value: number | boolean | null; new_value: number | boolean; reason: string | null;
  kind: "change" | "revert" | "kill_switch"; changed_by_name: string | null; created_at: string;
};

const base = () => `${getApiBaseUrl()}/api/v1`;
const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });

/** Turn a FastAPI error string (`API Error 422: {...}`) into readable issues. */
export function parseApiError(err: unknown): { message: string; issues: FormulaIssue[] } {
  const text = err instanceof Error ? err.message : String(err ?? "");
  const brace = text.indexOf("{");
  if (brace >= 0) {
    try {
      const detail = JSON.parse(text.slice(brace));
      if (detail && typeof detail === "object" && Array.isArray(detail.errors)) {
        return { message: String(detail.message ?? "Validation failed"), issues: detail.errors };
      }
      if (typeof detail === "string") return { message: detail, issues: [] };
    } catch { /* fall through to raw text */ }
  }
  return { message: text.replace(/^API Error \d+:\s*/, ""), issues: [] };
}

export const knowledgeApi = {
  parameters: () => requestJson<{ items: CatalogueParam[] }>(`${base()}/knowledge/parameters`, json("GET")),
  validateFormula: (formula: string) => requestJson<FormulaCheck>(`${base()}/knowledge/formula/validate`, json("POST", { formula })),
  listObjects: (q: { type?: string; status?: string; q?: string } = {}) => {
    const p = new URLSearchParams();
    Object.entries(q).forEach(([k, v]) => v && p.set(k, v));
    return requestJson<{ items: KbObject[] }>(`${base()}/knowledge/objects?${p}`, json("GET"));
  },
  getObject: (id: string) => requestJson<KbObject>(`${base()}/knowledge/objects/${id}`, json("GET")),
  versions: (type: string, code: string) =>
    requestJson<{ items: KbObject[] }>(`${base()}/knowledge/objects/${type}/${encodeURIComponent(code)}/versions`, json("GET")),
  create: (b: { type: KbType; code: string; name: string; scope: Record<string, string>; body: Record<string, unknown>; reason?: string }) =>
    requestJson<KbObject>(`${base()}/knowledge/objects`, json("POST", b)),
  update: (id: string, b: { name?: string; scope?: Record<string, string>; body?: Record<string, unknown>; reason?: string }) =>
    requestJson<KbObject>(`${base()}/knowledge/objects/${id}`, json("PUT", b)),
  clone: (id: string) => requestJson<KbObject>(`${base()}/knowledge/objects/${id}/clone`, json("POST")),
  submit: (id: string) => requestJson<KbObject>(`${base()}/knowledge/objects/${id}/submit`, json("POST")),
  trial: (id: string) => requestJson<KbObject>(`${base()}/knowledge/objects/${id}/trial`, json("POST")),
  publish: (id: string, override_reason?: string) =>
    requestJson<KbObject>(`${base()}/knowledge/objects/${id}/publish`, json("POST", { override_reason: override_reason || null })),
  retire: (id: string, reason: string) => requestJson<KbObject>(`${base()}/knowledge/objects/${id}/retire`, json("POST", { reason })),
  rollback: (id: string, reason: string) => requestJson<KbObject>(`${base()}/knowledge/objects/${id}/rollback`, json("POST", { reason })),
  preview: (id: string, params?: Record<string, number>) =>
    requestJson<{ results: PreviewRow[] }>(`${base()}/knowledge/objects/${id}/preview`, json("POST", { params: params ?? null })),
  similar: (text: string, type?: string) =>
    requestJson<{ items: { type: KbType; code: string; name: string; status: KbStatus; version: number; similarity: number }[] }>(
      `${base()}/knowledge/similar`, json("POST", { text, type: type ?? null })),
  registry: () => requestJson<Registry>(`${base()}/knowledge/registry`, json("GET")),
  seed: () => requestJson<{ created: number }>(`${base()}/knowledge/seed`, json("POST")),
  documents: () => requestJson<{ items: PolicyDocument[] }>(`${base()}/knowledge/documents`, json("GET")),
  analyzeDocument: (id: string) => requestJson<PolicyDocument>(`${base()}/knowledge/documents/${id}/analyze`, json("POST")),
  createDocument: (b: Record<string, unknown>) => requestJson<PolicyDocument>(`${base()}/knowledge/documents`, json("POST", b)),
  proposals: (q: { status?: string; source?: string; type?: string } = {}) => {
    const p = new URLSearchParams();
    Object.entries(q).forEach(([k, v]) => v && p.set(k, v));
    return requestJson<{ items: Proposal[] }>(`${base()}/knowledge/proposals?${p}`, json("GET"));
  },
  acceptProposal: (id: string) => requestJson<{ proposal: Proposal; object: KbObject }>(`${base()}/knowledge/proposals/${id}/accept`, json("POST")),
  editProposal: (id: string, payload: Record<string, unknown>) =>
    requestJson<{ proposal: Proposal; object: KbObject }>(`${base()}/knowledge/proposals/${id}/edit`, json("POST", { payload })),
  rejectProposal: (id: string, reason_code: string, note: string) =>
    requestJson<Proposal>(`${base()}/knowledge/proposals/${id}/reject`, json("POST", { reason_code, note })),
  config: () => requestJson<ConfigResponse>(`${base()}/agent-config`, json("GET")),
  setConfig: (key: string, value: number | boolean, reason: string) =>
    requestJson<{ value: number | boolean }>(`${base()}/agent-config/${key}`, json("PUT", { value, reason })),
  killSwitch: (enabled: boolean, reason: string) =>
    requestJson<{ value: boolean }>(`${base()}/agent-config/kill-switch`, json("POST", { enabled, reason })),
  configHistory: (key?: string) =>
    requestJson<{ items: ConfigHistory[] }>(`${base()}/agent-config/history/list${key ? `?key=${key}` : ""}`, json("GET")),
  revert: (id: string, reason: string) => requestJson<{ value: number | boolean }>(`${base()}/agent-config/history/${id}/revert`, json("POST", { reason })),
};
