import type { KbObject, KbStatus, KbType } from "@/lib/knowledge-client";
import type { Tone } from "@/lib/status-tone";

export const KSGL_ROLES = ["analyst", "fraud_analyst", "senior_analyst", "admin"] as const;
export const APPROVER_ROLES = ["senior_analyst", "admin"] as const;
export const KB_TYPES: KbType[] = ["motive", "behavior", "scenario", "workflow", "parameter"];
export const KB_STATUSES: KbStatus[] = ["draft", "ready_for_test", "trial", "published", "retired"];

export type Me = { id: string; roles: string[] };

const has = (roles: readonly string[], allowed: readonly string[]) => roles.some((r) => allowed.includes(r));
export const canAuthor = (roles: readonly string[]) => has(roles, KSGL_ROLES);
export const isApprover = (roles: readonly string[]) => has(roles, APPROVER_ROLES);

export const STATUS_TONE: Record<KbStatus, Tone> = {
  draft: "grey", ready_for_test: "amber", trial: "cyan", published: "green", retired: "brown",
};

/** Field holding the formula for each type (null = no formula). */
export function formulaField(type: KbType): "formula" | "condition" | null {
  return type === "motive" ? "formula" : type === "behavior" ? "condition" : null;
}

export function defaultBody(type: KbType): Record<string, unknown> {
  switch (type) {
    case "motive": return { beneficiary: "driver", policy: "", formula: "=", threshold_label: "" };
    case "behavior": return { description: "", signals: [], condition: "=", source_rule: "" };
    case "scenario": return { motive_code: "", behavior_code: "", reason: "", workflow_code: "" };
    case "workflow": return { ask_first: [], steps: [], stop_condition: "n_max", help_condition: "" };
    default: return { name: "", description: "", unit: "", source: "", owner: "", latency: "" };
  }
}

export type ObjectActions = {
  edit: boolean; submit: boolean; trial: boolean; publish: boolean; rollback: boolean; retire: boolean; clone: boolean;
  /** Why publish is unavailable although the object is in trial (4-eyes). */
  publishBlocked: "author" | "role" | null;
  needsOverride: boolean;
};

/** Mirrors the backend lifecycle rules so the UI offers only legal actions (server still enforces). */
export function objectActions(obj: KbObject, me: Me, hasUnpublishedSibling = false): ObjectActions {
  const author = canAuthor(me.roles);
  const approver = isApprover(me.roles);
  const isAuthor = obj.author_id !== null && obj.author_id === me.id;
  const inTrial = obj.status === "trial";
  const publishBlocked = inTrial && author ? (!approver ? "role" : isAuthor ? "author" : null) : null;
  return {
    edit: author && (obj.status === "draft" || obj.status === "ready_for_test"),
    submit: author && obj.status === "draft",
    trial: author && obj.status === "ready_for_test",
    publish: inTrial && approver && !isAuthor,
    rollback: obj.status === "published" && approver,
    retire: author && obj.status !== "retired",
    clone: author && !hasUnpublishedSibling,
    publishBlocked,
    needsOverride: inTrial && obj.replay !== null && !obj.replay.gate_passed,
  };
}

/** Split lines into a trimmed non-empty list (workflow ask-first editor). */
export const toLines = (text: string): string[] => text.split("\n").map((l) => l.trim()).filter(Boolean);

export const similarityPct = (v: number | null | undefined): string => (v == null ? "—" : `${Math.round(v * 100)}%`);

/** Highlight segments of a formula around an error position: [before, offending, after]. */
export function splitAtPosition(formula: string, position: number | undefined): [string, string, string] {
  if (position === undefined || position < 0 || position >= formula.length) return [formula, "", ""];
  const m = /^[A-Za-z_][A-Za-z0-9_]*|^\d+(?:\.\d+)?|^./.exec(formula.slice(position));
  const len = m ? m[0].length : 1;
  return [formula.slice(0, position), formula.slice(position, position + len), formula.slice(position + len)];
}
