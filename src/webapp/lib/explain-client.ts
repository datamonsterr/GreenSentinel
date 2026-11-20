import { getApiBaseUrl, requestJson } from "@/lib/api-client";
import { statusTone, type Tone } from "@/lib/status-tone";

/** Analyst/VH side of the driver explanation agent (ADR-034). The driver app uses lib/driver-explain-client.ts. */
export type RoundState = "eligible" | "not_eligible" | "needs_driver" | "missing_internal";
export const FLAG_KEYS = [
  "novel_scenario", "statement_changed", "ai_inconclusive", "session_interrupted", "asked_for_help", "asked_for_help_skipped",
] as const;
export type FlagKey = (typeof FLAG_KEYS)[number];
export const FEEDBACK_ERROR_TYPES = [
  "wrong_facts", "wrong_reasoning", "missing_question", "redundant_or_tone", "missing_tool_source", "wrong_scenario_or_workflow",
] as const;
export type FeedbackErrorType = (typeof FEEDBACK_ERROR_TYPES)[number];

export type StatementVersion = { version: number; source: string; reason: string | null; text: string | null; content: unknown; created_at: string };
export type AssessmentRound = {
  round: number; source: string; state: RoundState; matched_evidence: unknown; contradictions: unknown; open_points: unknown;
  missing_internal: unknown; statement_change: unknown; confidence: number | null; turns_used: number; n_max: number; llm_used: boolean; created_at: string;
};
export type ProvenanceItem = { type: string; code: string; version: number | string | null; tool?: string | null; turn_seq?: number | null; at?: string | null };
export type HelpRequest = {
  id: string; session_id: string; case_id: string; status: "open" | "claimed" | "replied" | "expired" | string; trigger: string | null;
  summary: string | null; stuck_point: string | null; facts: string[] | null; options: unknown; claimed_by_name: string | null; claimed_at: string | null;
  reply: string | null; reply_facts: string[]; replied_by_name: string | null; replied_at: string | null; wait_seconds: number | null;
  proposal_id: string | null; created_at: string; expires_at: string | null;
};
export type HelpRequestDetail = HelpRequest & {
  transcript: { seq: number; kind: string; text: string }[]; statement_text: string | null; reason: string | null;
};
export type Suggestion = {
  round: number; state: RoundState; reason_code: string | null; confidence: number | null; motive: unknown;
  suggested_questions: unknown; turns_used: number; n_max: number;
};
export type FeedbackEntry = {
  id: string; verdict: "agree" | "disagree"; error_types: string[]; comment: string | null; author_name: string | null; created_at: string;
};
export type ExplainView = {
  session: {
    id: string; case_id: string; reason: string; current_reason?: string; state: string; mode: string; scenario_code: string | null;
    scenario_version: number | null; workflow_code: string | null; workflow_version: number | null; turns_used: number; n_max: number;
    summary: string | null; submitted_at: string | null;
  };
  flags: Record<FlagKey, boolean>;
  form: unknown;
  statement_versions: StatementVersion[];
  rounds: AssessmentRound[];
  transcript: { seq: number; kind: string; visible_to_driver: boolean; text: string | null; tool: string | null; at: string }[];
  provenance: ProvenanceItem[];
  similar_scenarios: unknown[];
  plan: unknown;
  open_points: unknown;
  suggestion: Suggestion | null;
  help_requests: HelpRequest[];
  feedback: FeedbackEntry[];
};
export type HelpCounts = { open: number; claimed: number; total: number };
export type FeedbackBody = { verdict: "agree" | "disagree"; error_types: string[]; comment: string };

const ROUND_TONE: Record<string, Tone> = { eligible: "green", not_eligible: "red", needs_driver: "amber", missing_internal: "grey" };
const FLAG_TONE: Record<string, Tone> = {
  novel_scenario: "purple", statement_changed: "amber", ai_inconclusive: "orange", session_interrupted: "red",
  asked_for_help: "cyan", asked_for_help_skipped: "grey",
};
export const roundStateTone = (state: string): string => statusTone(ROUND_TONE[state] ?? "grey");
export const flagTone = (flag: string): string => statusTone(FLAG_TONE[flag] ?? "grey");

const FEEDBACK_ROLES = ["analyst", "senior_analyst", "fraud_analyst", "admin"];
/** reviewer / ops_director see the section read-only (ADR-031/032). */
export const canGiveFeedback = (roles: readonly string[] | null | undefined): boolean => (roles ?? []).some((r) => FEEDBACK_ROLES.includes(r));
/** Analyst stands in for VH on the help queue. */
export const canUseHelpQueue = canGiveFeedback;

/** Newest feedback entry per author (feedback is append-only). */
export function latestFeedbackPerAuthor(items: readonly FeedbackEntry[]): FeedbackEntry[] {
  const latest = new Map<string, FeedbackEntry>();
  for (const f of items) {
    const key = f.author_name ?? "";
    const prev = latest.get(key);
    if (!prev || f.created_at >= prev.created_at) latest.set(key, f);
  }
  return [...latest.values()].sort((a, b) => b.created_at.localeCompare(a.created_at));
}

export type DiffLine = { op: "same" | "add" | "del"; text: string };
const lines = (s: string | null | undefined) => (s ?? "").split("\n").map((l) => l.trim()).filter(Boolean);

/** Line diff (LCS) between two statement texts, for the version compare view. */
export function diffStatements(before: string | null | undefined, after: string | null | undefined): DiffLine[] {
  const a = lines(before);
  const b = lines(after);
  const dp = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) for (let j = b.length - 1; j >= 0; j--) {
    dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  }
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) { out.push({ op: "same", text: a[i] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) out.push({ op: "del", text: a[i++] });
    else out.push({ op: "add", text: b[j++] });
  }
  while (i < a.length) out.push({ op: "del", text: a[i++] });
  while (j < b.length) out.push({ op: "add", text: b[j++] });
  return out;
}

/** 404 = the case has no explanation session (section stays hidden). */
export function isNoSession(err: unknown): boolean {
  if (err && typeof err === "object" && "status" in err && (err as { status?: unknown }).status === 404) return true;
  return /API Error 404/.test(err instanceof Error ? err.message : String(err ?? ""));
}

const base = () => `${getApiBaseUrl()}/api/v1`;
const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });
const enc = encodeURIComponent;

export const explainApi = {
  get: (caseId: string) => requestJson<ExplainView>(`${base()}/cases/${enc(caseId)}/explain`, json("GET")),
  feedback: (caseId: string, body: FeedbackBody) => requestJson<FeedbackEntry>(`${base()}/cases/${enc(caseId)}/explain/feedback`, json("POST", body)),
  helpCount: () => requestJson<HelpCounts>(`${base()}/explain/help-requests/count`, json("GET")),
  helpList: (status = "open,claimed") =>
    requestJson<{ items: HelpRequest[]; counts: HelpCounts }>(`${base()}/explain/help-requests?${new URLSearchParams({ status })}`, json("GET")),
  helpDetail: (id: string) => requestJson<HelpRequestDetail>(`${base()}/explain/help-requests/${enc(id)}`, json("GET")),
  claim: (id: string) => requestJson<HelpRequest>(`${base()}/explain/help-requests/${enc(id)}/claim`, json("POST")),
  reply: (id: string, text: string, facts: string[]) =>
    requestJson<HelpRequest>(`${base()}/explain/help-requests/${enc(id)}/reply`, json("POST", { text, facts })),
};
