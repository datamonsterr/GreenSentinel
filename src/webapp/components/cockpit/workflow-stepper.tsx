"use client";

import React, { useCallback, useEffect, useState } from "react";
import { advanceCaseWorkflow, fetchCaseWorkflow, type CaseWorkflow, type WorkflowStep } from "@/lib/case-workflow-client";
import { actorStyle } from "@/lib/role-style";
import type { Locale } from "@/lib/locale";

const L = {
  vi: {
    title: "Tiến trình xử lý", next: "Bước tiếp theo", closed: "Hồ sơ đã đóng · không vi phạm", done: "Hoàn tất",
    err: "Không tải được tiến trình", act: {
      "issue-report": "Phát hành biên bản", "confirm-report": "Xác nhận biên bản",
      "approve-ops": "OPS DIR duyệt", "approve-marketplace": "MKP DIR duyệt",
    } as Record<string, string>,
  },
  en: {
    title: "Workflow progress", next: "Next step", closed: "Case closed · no violation", done: "Done",
    err: "Could not load workflow", act: {
      "issue-report": "Issue report", "confirm-report": "Confirm report",
      "approve-ops": "OPS DIR approve", "approve-marketplace": "MKP DIR approve",
    } as Record<string, string>,
  },
} as const;

const fmt = (iso: string | null, locale: Locale) =>
  iso ? new Date(iso).toLocaleString(locale === "vi" ? "vi-VN" : "en-GB", { dateStyle: "short", timeStyle: "short" }) : "";

const DOT: Record<WorkflowStep["state"], string> = {
  done: "bg-gs-green border-gs-green text-white",
  current: "bg-white border-gs-cyan text-gs-cyan ring-4 ring-gs-cyan-soft",
  pending: "bg-white border-gs-line-2 text-gs-mute",
};

/** Presentational stepper — all state comes from the backend payload. */
export function WorkflowStepperView({
  workflow, locale, busy, onAction,
}: { workflow: CaseWorkflow; locale: Locale; busy?: boolean; onAction?: (a: string) => void }) {
  const m = L[locale];
  const next = workflow.next;
  const nextRole = next ? actorStyle(next.actor_role) : null;
  return (
    <section aria-label={m.title} data-testid="workflow-stepper" className="mb-3 rounded-xl border border-gs-line bg-white p-3">
      <h3 className="mb-2 text-xs font-bold uppercase tracking-wide text-gs-mute-2">{m.title}</h3>
      <ol className="flex items-start overflow-x-auto pb-1">
        {workflow.steps.map((s, i) => {
          const role = actorStyle(s.actor_role);
          return (
            <li key={s.key} data-step={s.key} data-state={s.state} aria-current={s.state === "current" ? "step" : undefined}
              className="relative flex min-w-[92px] flex-1 flex-col items-center px-1 text-center">
              {i > 0 && <span aria-hidden className={`absolute right-1/2 top-3 h-0.5 w-full ${s.state === "pending" ? "bg-gs-line-2" : "bg-gs-green"}`} />}
              <span className={`relative z-10 flex h-6 w-6 items-center justify-center rounded-full border-2 text-[11px] font-bold ${DOT[s.state]}`}>
                {s.state === "done" ? "✓" : i + 1}
              </span>
              <span className={`mt-1 text-[11px] leading-tight ${s.state === "pending" ? "text-gs-mute" : "font-semibold text-gs-ink"}`}>{s.label}</span>
              <span className="mt-1 rounded-full px-1.5 py-px text-[10px] font-bold" style={{ background: role.bg, color: role.fg }} title={s.actor_role === "MKP_DIR" ? "Admin" : undefined}>{role.label}</span>
              {s.actor_role === "MKP_DIR" && <span className="text-[10px] text-gs-mute">Admin</span>}
              {s.state === "done" && s.completed_at && <span className="mt-0.5 text-[10px] text-gs-mute">{fmt(s.completed_at, locale)}</span>}
            </li>
          );
        })}
      </ol>
      {workflow.closed && <p className="mt-2 rounded-lg bg-slate-100 px-2.5 py-1.5 text-xs text-gs-mute-2">{m.closed}</p>}
      {next && nextRole && (
        <div data-testid="workflow-next" className="mt-2 flex flex-wrap items-center gap-2 rounded-lg bg-gs-cyan-soft px-2.5 py-1.5 text-xs text-gs-ink">
          <span className="font-semibold">{m.next}:</span>
          <span className="rounded-full px-2 py-px text-[10px] font-bold" style={{ background: nextRole.bg, color: nextRole.fg }}>{nextRole.label}</span>
          <span>— {next.text}</span>
          {(workflow.actions ?? []).map((a) => (
            <button key={a} type="button" disabled={busy} onClick={() => onAction?.(a)}
              className="ml-auto rounded-md bg-gs-cyan px-2.5 py-1 text-xs font-semibold text-white disabled:opacity-50">{m.act[a] ?? a}</button>
          ))}
        </div>
      )}
    </section>
  );
}

export function WorkflowStepper({ caseId, locale, refreshKey }: { caseId: string; locale: Locale; refreshKey?: unknown }) {
  const [wf, setWf] = useState<CaseWorkflow | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    fetchCaseWorkflow(caseId).then((w) => { if (!Array.isArray(w?.steps)) throw new Error("bad workflow payload"); if (live) { setWf(w); setFailed(false); } }).catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, [caseId, refreshKey]);
  const act = useCallback(async (a: string) => {
    setBusy(true);
    try { const w = await advanceCaseWorkflow(caseId, a); if (!Array.isArray(w?.steps)) throw new Error("bad workflow payload"); setWf(w); setFailed(false); } catch { setFailed(true); } finally { setBusy(false); }
  }, [caseId]);
  if (!wf) return failed ? <p data-testid="workflow-error" className="mb-3 text-xs text-gs-mute">{L[locale].err}</p> : null;
  return <WorkflowStepperView workflow={wf} locale={locale} busy={busy} onAction={act} />;
}
