"use client";

import React from "react";
import type { CaseDetailResponse } from "@/types/schemas";
import { caseStatusTone } from "@/lib/status-tone";
import { formatDuration } from "@/lib/cockpit-signals";
import type { Locale } from "@/lib/locale";
import { CopyId } from "./copy-id";

const L = {
  vi: {
    title: "Thông tin hồ sơ", caseSec: "Hồ sơ", driver: "Thông tin tài xế", trip: "Thông tin chuyến", rules: "Quy tắc & xử lý",
    caseId: "Mã hồ sơ", status: "Trạng thái", priority: "Ưu tiên", category: "Phân loại", assignee: "Người xử lý", sla: "SLA còn lại",
    opened: "Mở lúc", updated: "Cập nhật", dispute: "Giải trình", deadline: "Hạn giải trình", confidence: "Độ tin cậy AI",
    driverName: "Tên tài xế", driverRef: "Mã tài xế", plate: "Biển số", model: "Mẫu xe", driverStatus: "Trạng thái TX", totalTrips: "Tổng cuốc", rating: "Đánh giá",
    tripId: "Mã chuyến", requested: "Thời gian đặt", arrived: "Đến điểm đón", ended: "Kết thúc", route: "Lộ trình", district: "Quận/Huyện",
    fare: "Giá cước", fareDelta: "Chênh lệch cước", routeKm: "Quãng đường tuyến", stall: "Thời gian dừng",
    ruleVer: "Phiên bản chính sách", reasons: "Mã quy tắc kích hoạt", action: "Mức xử lý theo ma trận", unassigned: "Chưa phân công", none: "—", overdue: "Quá hạn",
  },
  en: {
    title: "Case information", caseSec: "Case", driver: "Driver", trip: "Trip", rules: "Rules & action",
    caseId: "Case ID", status: "Status", priority: "Priority", category: "Category", assignee: "Assignee", sla: "SLA remaining",
    opened: "Opened", updated: "Updated", dispute: "Dispute", deadline: "Dispute deadline", confidence: "AI confidence",
    driverName: "Driver", driverRef: "Driver ID", plate: "Plate", model: "Vehicle model", driverStatus: "Driver status", totalTrips: "Total trips", rating: "Rating",
    tripId: "Trip ID", requested: "Requested", arrived: "Arrived", ended: "Ended", route: "Route", district: "District",
    fare: "Fare", fareDelta: "Fare delta", routeKm: "Route distance", stall: "Stall time",
    ruleVer: "Policy version", reasons: "Triggered rule codes", action: "Matrix action", unassigned: "Unassigned", none: "—", overdue: "Overdue",
  },
} as const;

const dash = "—";
const fmtDate = (v: unknown, locale: Locale) => {
  if (!v) return dash;
  const d = new Date(String(v));
  return Number.isNaN(d.getTime()) ? dash : d.toLocaleString(locale === "vi" ? "vi-VN" : "en-GB", { dateStyle: "short", timeStyle: "short" });
};
const vnd = (v: unknown, locale: Locale) => (typeof v === "number" ? `${v.toLocaleString(locale === "vi" ? "vi-VN" : "en-US")} VNĐ` : dash);

function Kv({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 truncate text-[12.5px]" >
      <span className="text-gs-mute">{k}:</span>&nbsp;<span className="font-bold text-on-surface">{children}</span>
    </div>
  );
}

function Sec({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-gs-line py-2 first:border-t-0 first:pt-0">
      <h3 className="mb-1 text-[11px] font-extrabold uppercase tracking-wide text-on-surface">{title}</h3>
      <div className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2">{children}</div>
    </section>
  );
}

export function CaseMetadata({ caseDetail, locale }: { caseDetail: CaseDetailResponse; locale: Locale }) {
  const [collapsed, setCollapsed] = React.useState(false);
  const m = L[locale];
  const c = caseDetail.case;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const t = (caseDetail.trip ?? {}) as Record<string, any>;
  const policy = caseDetail.case_policy;
  const sla = c.sla_countdown_s;
  const route = caseDetail.candidate_routes?.[0];
  const action = policy?.applicable_action_rule && Object.keys(policy.applicable_action_rule).length
    ? (policy.applicable_action_rule.action ?? policy.applicable_action_rule.sanction ?? policy.applicable_action_rule.recommended_action) : null;
  return (
    <div data-testid="case-metadata" className="mb-2 rounded-xl border border-gs-line bg-white p-3">
      <button type="button" aria-label={m.title} aria-expanded={!collapsed} onClick={() => setCollapsed(!collapsed)} className="flex w-full flex-wrap items-center gap-2 text-left text-[12.5px]">
        <span className="text-[11px] font-extrabold uppercase tracking-wide text-on-surface">{m.title}</span>
        <span className={`gs-tone pill ${caseStatusTone(c.status)}`}>{c.status}</span>
        <span className="font-bold">{c.driver_name ?? t.driver_name ?? dash}</span>
        <span className="text-gs-mute">{c.vehicle_plate ?? t.vehicle_plate ?? ""}</span>
        <span className="ml-auto text-gs-mute">{collapsed ? "▸" : "▾"}</span>
      </button>
      {!collapsed && <div className="mt-2">
      <Sec title={m.caseSec}>
        <Kv k={m.caseId}><CopyId id={c.id} label={m.caseId} displayId={`#${c.id.slice(-8)}`} /></Kv>
        <Kv k={m.status}>{c.status}</Kv>
        <Kv k={m.priority}>{c.priority}{typeof c.priority_score === "number" ? ` · ${c.priority_score}` : ""}</Kv>
        <Kv k={m.assignee}>{c.assigned_analyst_name ?? m.unassigned}</Kv>
        <Kv k={m.sla}>{sla == null ? dash : sla === 0 ? <span className="text-gs-red">{m.overdue}</span> : formatDuration(sla)}</Kv>
        <Kv k={m.opened}>{fmtDate(c.opened_at, locale)}</Kv>
        <Kv k={m.updated}>{fmtDate(c.updated_at, locale)}</Kv>
        <Kv k={m.confidence}>{typeof c.confidence === "number" ? `${Math.round(c.confidence <= 1 ? c.confidence * 100 : c.confidence)}%` : dash}</Kv>
        {c.dispute_status && c.dispute_status !== "not_disputed" && <Kv k={m.dispute}>{c.dispute_status}</Kv>}
        {c.dispute_deadline && <Kv k={m.deadline}>{fmtDate(c.dispute_deadline, locale)}</Kv>}
      </Sec>
      <Sec title={m.driver}>
        <Kv k={m.driverName}>{t.driver_name ?? c.driver_name ?? dash}</Kv>
        <Kv k={m.driverRef}>{t.driver_ref ?? c.driver_id ?? dash}</Kv>
        <Kv k={m.plate}>{t.vehicle_plate ?? c.vehicle_plate ?? dash}</Kv>
        <Kv k={m.model}>{t.vehicle_model ?? t.vehicle_type ?? dash}</Kv>
        <Kv k={m.driverStatus}>{t.driver_status ?? dash}</Kv>
        <Kv k={m.totalTrips}>{t.total_trips ?? dash}</Kv>
        <Kv k={m.rating}>{typeof t.rating === "number" ? t.rating.toFixed(1) : dash}</Kv>
      </Sec>
      <Sec title={m.trip}>
        <Kv k={m.tripId}>{t.id ? <CopyId id={String(t.id)} label={m.tripId} /> : dash}</Kv>
        <Kv k={m.requested}>{fmtDate(t.requested_at, locale)}</Kv>
        <Kv k={m.arrived}>{fmtDate(t.arrived_at, locale)}</Kv>
        <Kv k={m.ended}>{fmtDate(t.ended_at ?? t.completed_at, locale)}</Kv>
        <Kv k={m.route}>{t.pickup_address || t.dropoff_address ? `${t.pickup_address ?? dash} → ${t.dropoff_address ?? dash}` : dash}</Kv>
        <Kv k={m.district}>{t.district ?? c.district ?? dash}</Kv>
        <Kv k={m.fare}>{vnd(t.fare_amount_vnd, locale)}</Kv>
        <Kv k={m.fareDelta}>{vnd(t.fare_delta_vnd, locale)}</Kv>
        <Kv k={m.routeKm}>{route ? `${(route.distance_m / 1000).toFixed(1)} km` : dash}</Kv>
        <Kv k={m.stall}>{c.stall_duration_s != null ? formatDuration(c.stall_duration_s) : dash}</Kv>
      </Sec>
      <Sec title={m.rules}>
        <Kv k={m.ruleVer}>{policy?.policy_version ?? dash}</Kv>
        <Kv k={m.action}>{action ? String(action) : dash}</Kv>
      </Sec>
      </div>}
    </div>
  );
}
