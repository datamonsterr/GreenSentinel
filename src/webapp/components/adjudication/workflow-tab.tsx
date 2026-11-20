"use client";

import React, { useEffect, useRef, useState } from "react";
import type { CaseDetailResponse, WorkflowTrace } from "@/types/schemas";
import { useLocale } from "@/lib/locale";
import { saveCaseWorkflowDraft } from "@/lib/api-client";
import { BadgePercent, CircleDot, ScrollText, UserCheck, Workflow, Wrench } from "lucide-react";
import { IconTile } from "@/components/cockpit/icon-tile";
import { MetricCard } from "@/components/cockpit/metric-card";
import { MetricGrid } from "@/components/cockpit/metric-grid";
import { SectionCard } from "@/components/cockpit/section-card";
import { EmptyState } from "@/components/cockpit/empty-state";

interface WorkflowTabProps {
  caseDetail: CaseDetailResponse;
  caseWorkflowTrace?: WorkflowTrace | null;
  aiRevealed?: boolean;
  canWrite?: boolean;
}

const copy = {
  en: { title: "Workflow", aiResults: "AI results", local: "Local draft — not saved", draft: "Workflow draft", save: "Save draft", saving: "Saving…", saved: "Draft saved", timeline: "Timeline", tools: "Tools", policies: "Policies", finalDecision: "Final decision", recorded: "Recorded workflow event", recordedTool: "Recorded tool activity", unavailable: "No recorded workflow events.", readOnly: "Claim the case to edit the draft.", events: "Workflow events", toolsCalled: "Tools called", actions: "Human actions", confidence: "AI confidence" },
  vi: { title: "Quy trình", aiResults: "Kết quả AI", local: "Bản nháp cục bộ — chưa lưu", draft: "Bản nháp quy trình", save: "Lưu bản nháp", saving: "Đang lưu…", saved: "Đã lưu bản nháp", timeline: "Dòng thời gian", tools: "Công cụ", policies: "Quy định", finalDecision: "Quyết định cuối", recorded: "Sự kiện quy trình đã ghi nhận", recordedTool: "Hoạt động công cụ đã ghi nhận", unavailable: "Chưa có sự kiện quy trình.", readOnly: "Hãy nhận vụ việc để chỉnh sửa bản nháp.", events: "Sự kiện quy trình", toolsCalled: "Công cụ đã gọi", actions: "Thao tác của người", confidence: "Độ tin cậy AI" },
} as const;

export const WorkflowTab: React.FC<WorkflowTabProps> = ({ caseDetail, caseWorkflowTrace, aiRevealed = false, canWrite = false }) => {
  const { locale } = useLocale();
  const t = copy[locale];
  const workflow: any = caseWorkflowTrace || (caseDetail.case as any)?.workflow_trace;
  const caseId = String(caseDetail.case?.id || "");
  const serverVersion = caseDetail.workflow_draft?.version ?? 0;
  const [draft, setDraft] = useState("");
  const [version, setVersion] = useState(serverVersion);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const identityRef = useRef(caseId);

  useEffect(() => {
    identityRef.current = caseId;
    setDraft(caseDetail.workflow_draft?.text ?? caseDetail.workflow_draft?.summary ?? caseDetail.workflow_draft?.draft ?? "");
    setVersion(serverVersion);
    setSaving(false);
    setError(null);
    setSaved(false);
  }, [caseId]);

  const save = async () => {
    if (!canWrite || saving || draft.length > 20000 || !caseId) return;
    const target = caseId;
    setSaving(true); setError(null); setSaved(false);
    try {
      const result = await saveCaseWorkflowDraft(target, draft, version);
      if (identityRef.current !== target) return;
      setVersion(result.version);
      setDraft(result.text);
      setDirty(false);
      setSaved(true);
    } catch (reason) {
      if (identityRef.current === target) setError(reason instanceof Error ? reason.message : "Unable to save workflow draft");
    } finally {
      if (identityRef.current === target) setSaving(false);
    }
  };

  const terminal = ["resolved", "dismissed", "auto_dismissed"].includes(String(caseDetail.case.status || "").toLowerCase());
  const writable = canWrite && !terminal;
  const timeline = workflow?.timeline || [];
  const tools = workflow?.agent_tools_called || [];
  const humanActions = workflow?.human_actions_performed || [];
  const policies = aiRevealed ? workflow?.related_policies || [] : [];
  const confidence = aiRevealed && typeof workflow?.ai_result?.confidence === "number"
    ? Math.round(workflow.ai_result.confidence * (workflow.ai_result.confidence <= 1 ? 100 : 1))
    : null;
  return <section role="region" aria-label={t.title} className="space-y-3">
    <MetricGrid columns={aiRevealed ? 4 : 3}>
      <MetricCard icon={Workflow} tone="info" label={t.events} value={String(timeline.length)} />
      <MetricCard icon={Wrench} tone="violet" label={t.toolsCalled} value={String(tools.length)} />
      <MetricCard icon={UserCheck} tone="success" label={t.actions} value={String(humanActions.length)} />
      {aiRevealed && <MetricCard icon={BadgePercent} tone="warning" label={t.confidence} value={confidence === null ? null : `${confidence}%`} />}
    </MetricGrid>
    <SectionCard aria-label={undefined} icon={Workflow} tone="info" title={t.title} subtitle={!caseDetail.workflow_draft ? t.local : undefined} bodyClassName="space-y-3">
      {!writable && <p className="text-xs text-slate-500">{t.readOnly}</p>}
      <label className="block text-xs font-semibold text-slate-700">{t.draft}
        <textarea rows={2} maxLength={20000} disabled={!writable || saving} className="mt-1 min-h-16 w-full resize-y rounded-md border border-slate-300 bg-slate-50 p-2 text-[13px] font-normal outline-none focus:border-primary focus:ring-2 focus:ring-primary/30 disabled:bg-slate-100" aria-label={t.draft} value={draft} onChange={event => { setDraft(event.target.value); setDirty(true); setSaved(false); }} />
      </label>
      <div className="flex items-center gap-2"><button type="button" onClick={() => void save()} disabled={!writable || saving || draft.length > 20000} className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-container disabled:opacity-50">{saving ? t.saving : t.save}</button>{saved && <span role="status" className="text-xs text-gs-green-ink">{t.saved}</span>}{error && <span role="alert" className="text-xs text-gs-red">{error}</span>}</div>
      <section aria-label={t.timeline}>
        <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">{t.timeline}</h3>
        {timeline.length ? (
          <ol className="space-y-2">
            {timeline.map((event: any, index: number) => (
              <li key={`${event.event_type || event.label || "event"}-${index}`} className="flex items-center gap-3 rounded-lg border border-slate-100 bg-slate-50/60 p-2">
                <IconTile icon={CircleDot} tone="info" size="sm" />
                <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-slate-900">{aiRevealed ? (event.label || event.event_type) : t.recorded}</span>
                {event.occurred_at && <time dateTime={event.occurred_at} className="shrink-0 font-mono text-[11px] text-slate-500">{event.occurred_at}</time>}
              </li>
            ))}
          </ol>
        ) : <EmptyState compact icon={Workflow} hint={t.unavailable} />}
      </section>
      {tools.length > 0 && (
        <section aria-label={t.tools}>
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">{t.tools}</h3>
          <ol className="space-y-2">
            {tools.map((tool: any, index: number) => (
              <li key={`${tool.tool_name || "tool"}-${index}`} className="flex items-center gap-3 rounded-lg border border-slate-100 bg-slate-50/60 p-2">
                <IconTile icon={Wrench} tone="violet" size="sm" />
                <div className="min-w-0 flex-1">
                  {aiRevealed ? <>
                    <p className="flex min-w-0 items-center gap-2"><span className="truncate rounded border border-slate-200 bg-white px-1.5 py-0.5 font-mono text-[11px] text-slate-700">{tool.tool_name}</span><span className="shrink-0 text-[11px] text-slate-500">{tool.status}</span></p>
                    {tool.output_summary && <p className="mt-1 text-[13px] text-slate-700">{tool.output_summary}</p>}
                  </> : <p className="text-[13px] text-slate-700">{t.recordedTool}</p>}
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}
      {policies.length > 0 && (
        <section aria-label={t.policies}>
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">{t.policies}</h3>
          <ul className="space-y-1.5">
            {policies.map((policy: any) => <li key={`${policy.policy_code}-${policy.clause}`} className="flex items-start gap-2 text-[13px] text-slate-700"><ScrollText aria-hidden="true" size={14} className="mt-1 block shrink-0 text-gs-blue" /><span>{policy.policy_code} · {policy.clause}: {policy.rationale}</span></li>)}
          </ul>
        </section>
      )}
      {aiRevealed && workflow?.final_decision && <section aria-label={t.finalDecision}><h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">{t.finalDecision}</h3><p className="text-[13px] text-slate-800">{workflow.final_decision.verdict} · {workflow.final_decision.rationale}</p></section>}
      {aiRevealed && workflow?.ai_result && <section aria-label={t.aiResults} className="rounded-md border border-gs-cyan/30 bg-gs-cyan-soft/60 p-2 text-[13px] text-slate-800">{workflow.ai_result.classification} {workflow.ai_result.confidence}</section>}
    </SectionCard>
  </section>;
};
