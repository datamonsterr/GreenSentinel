"use client";

import React from "react";
import type { CaseDetailResponse } from "@/types/schemas";
import { useLocale, type Locale } from "@/lib/locale";
import { workspaceState } from "@/lib/workspace-messages";
import { formatDuration } from "@/lib/cockpit-signals";

const L = {
  vi: {
    assignee: "Người xử lý", unassigned: "Chưa phân công", sla: "SLA còn lại", overdue: "Quá hạn", priority: "Ưu tiên", status: "Trạng thái",
    policy: "Phiên bản chính sách", action: "Mức xử lý theo ma trận", dispute: "Giải trình", deadline: "Hạn giải trình",
    requested: "Đặt", arrived: "Đến điểm đón", ended: "Kết thúc", district: "Quận/Huyện", fareDelta: "Chênh lệch cước", routeKm: "Quãng đường tuyến",
  },
  en: {
    assignee: "Assignee", unassigned: "Unassigned", sla: "SLA remaining", overdue: "Overdue", priority: "Priority", status: "Status",
    policy: "Policy version", action: "Matrix action", dispute: "Dispute", deadline: "Dispute deadline",
    requested: "Requested", arrived: "Arrived", ended: "Ended", district: "District", fareDelta: "Fare delta", routeKm: "Route distance",
  },
} as const;

type Fact = { label: string; value: React.ReactNode | null | undefined };

const when = (v: unknown, locale: Locale) => {
  if (!v) return null;
  const d = new Date(String(v));
  return Number.isNaN(d.getTime()) ? null : d.toLocaleString(locale === "vi" ? "vi-VN" : "en-GB", { dateStyle: "short", timeStyle: "short" });
};

/** Compact label/value chips; empty values are skipped. */
export function FactChips({ facts, testId }: { facts: Fact[]; testId: string }) {
  const shown = facts.filter(f => f.value !== null && f.value !== undefined && f.value !== "");
  if (!shown.length) return null;
  return (
    <div data-testid={testId} className="flex flex-wrap gap-1.5">
      {shown.map(f => (
        <span key={f.label} className="inline-flex min-w-0 max-w-full items-center gap-1 rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[12px] shadow-2xs">
          <span className="shrink-0 text-slate-500">{f.label}:</span>
          <span className="truncate font-semibold text-slate-900">{f.value}</span>
        </span>
      ))}
    </div>
  );
}

/** Case-level facts for the Complete tab: status, priority, assignee, SLA, policy, matrix action. */
export function CaseLevelFacts({ caseDetail }: { caseDetail: CaseDetailResponse }) {
  const { locale } = useLocale();
  const m = L[locale];
  const c = caseDetail.case;
  const policy = caseDetail.case_policy;
  const rule = policy?.applicable_action_rule ?? {};
  const action = rule.action ?? rule.sanction ?? rule.recommended_action;
  const sla = c.sla_countdown_s;
  return (
    <FactChips testId="case-level-facts" facts={[
      { label: m.status, value: c.status ? workspaceState(c.status, locale) : null },
      { label: m.priority, value: c.priority ? `${c.priority}${typeof c.priority_score === "number" ? ` · ${c.priority_score}` : ""}` : null },
      { label: m.assignee, value: c.assigned_analyst_name ?? m.unassigned },
      { label: m.sla, value: sla == null ? null : sla === 0 ? <span className="text-red-700">{m.overdue}</span> : formatDuration(sla) },
      { label: m.policy, value: policy?.policy_version },
      { label: m.action, value: action ? String(action) : null },
    ]} />
  );
}

/** Dispute status and deadline for the Customer tab. */
export function DisputeFacts({ caseDetail }: { caseDetail: CaseDetailResponse }) {
  const { locale } = useLocale();
  const m = L[locale];
  const c = caseDetail.case;
  return (
    <FactChips testId="dispute-facts" facts={[
      { label: m.dispute, value: c.dispute_status ? workspaceState(c.dispute_status, locale) : null },
      { label: m.deadline, value: when(c.dispute_deadline, locale) },
    ]} />
  );
}

/** Trip timing/route facts not already in the strip or KPI cards. */
export function TripExtraFacts({ caseDetail }: { caseDetail: CaseDetailResponse }) {
  const { locale } = useLocale();
  const m = L[locale];
  const trip = caseDetail.trip;
  const km = caseDetail.candidate_routes?.[0]?.distance_m;
  const delta = trip?.fare_delta_vnd;
  return (
    <FactChips testId="trip-extra-facts" facts={[
      { label: m.requested, value: when(trip?.requested_at, locale) },
      { label: m.arrived, value: when(trip?.arrived_at, locale) },
      { label: m.ended, value: when(trip?.ended_at ?? trip?.completed_at, locale) },
      { label: m.district, value: trip?.district ?? caseDetail.case.district },
      { label: m.fareDelta, value: typeof delta === "number" ? `${delta.toLocaleString(locale === "vi" ? "vi-VN" : "en-US")} ₫` : null },
      { label: m.routeKm, value: typeof km === "number" ? `${(km / 1000).toFixed(1)} km` : null },
    ]} />
  );
}
