import { ApiError, getApiBaseUrl, requestJson } from "@/lib/api-client";

export type ExplainReason = "NotDone" | "RealTrip" | "Tech" | "Customer" | "Other";
export type ExplainFieldType = "text" | "time" | "location" | "choice" | "amount" | "photo" | "ticket";
export type Bilingual = { vi: string; en: string };
export type ExplainField = {
  id: string;
  label: Bilingual;
  type: ExplainFieldType;
  required: boolean;
  options?: { value: string; label?: Bilingual }[];
};
export type ExplainAnswers = Record<string, unknown>;
export type ExplainMessage = { seq: number; role: "agent" | "driver"; text: string; is_summary?: boolean };
export type ExplainUiStatus = "form" | "checking" | "chat" | "summary" | "submitted";

export type ExplainView = {
  session_id: string;
  state: string;
  ui_status: ExplainUiStatus;
  mode: "agent" | "fallback";
  reason: ExplainReason;
  form: { form_version: string; has_question_set: boolean; fields: ExplainField[]; answers: ExplainAnswers };
  messages: ExplainMessage[];
  current_question: { seq: number; text: string } | null;
  waiting_for_help: boolean;
  can_end: boolean;
  summary: string | null;
  edits_left: number;
  status_text: Bilingual | null;
  idle_timeout_minutes: number;
};

export type FormInvalid = { missing: string[]; invalid: { field: string; code: string }[] };

const url = (caseId: string, path = "") => `${getApiBaseUrl()}/api/v1/driver/cases/${encodeURIComponent(caseId)}/explain${path}`;
const send = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });

export const driverExplainClient = {
  get: (caseId: string) => requestJson<ExplainView>(url(caseId), send("GET")),
  start: (caseId: string, reason: ExplainReason) => requestJson<ExplainView>(url(caseId, "/start"), send("POST", { reason })),
  saveDraft: (caseId: string, answers: ExplainAnswers) => requestJson<ExplainView>(url(caseId, "/draft"), send("PUT", { answers })),
  submit: (caseId: string, answers: ExplainAnswers) => requestJson<ExplainView>(url(caseId, "/submit"), send("POST", { answers })),
  answer: (caseId: string, text: string, attachments: string[] = [], ticketCode?: string) =>
    requestJson<ExplainView>(url(caseId, "/answer"), send("POST", { text, attachments, ticket_code: ticketCode })),
  end: (caseId: string) => requestJson<ExplainView>(url(caseId, "/end"), send("POST")),
  editSummary: (caseId: string, text: string) => requestJson<ExplainView>(url(caseId, "/summary/edit"), send("POST", { text })),
  confirm: (caseId: string) => requestJson<ExplainView>(url(caseId, "/summary/confirm"), send("POST")),
};

/** Parse the `form_invalid` 422 detail carried inside an ApiError message. */
export function parseFormInvalid(err: unknown): FormInvalid | null {
  if (!(err instanceof ApiError) || err.status !== 422) return null;
  const brace = err.message.indexOf("{");
  if (brace < 0) return null;
  try {
    const d = JSON.parse(err.message.slice(brace));
    if (d?.code !== "form_invalid") return null;
    return { missing: Array.isArray(d.missing) ? d.missing : [], invalid: Array.isArray(d.invalid) ? d.invalid : [] };
  } catch {
    return null;
  }
}

/** 409 detail.code (not_asking, waiting_for_help, ...) or null. */
export function conflictCode(err: unknown): string | null {
  if (!(err instanceof ApiError) || err.status !== 409) return null;
  const m = /"code"\s*:\s*"([a-z_]+)"/.exec(err.message);
  return m ? m[1] : null;
}

export function pick(b: Bilingual | undefined, locale: string): string {
  if (!b) return "";
  return (locale === "en" ? b.en : b.vi) || b.vi || b.en;
}
