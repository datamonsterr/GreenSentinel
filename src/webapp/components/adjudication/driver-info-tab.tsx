"use client";

import React, { useEffect, useState } from "react";
import type { CaseDetailResponse, DriverPastIncident, DriverScorecardResponse, FraudCaseSummary } from "@/types/schemas";
import { fetchCaseDriverScorecard, fetchDriverScorecard } from "@/lib/api-client";
import { useLocale } from "@/lib/locale";
import { workspaceState } from "@/lib/workspace-messages";
import { cn } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { BarChart3, CalendarClock, Quote, CircleCheck, CircleX, Crosshair, History, Receipt, Route, Star, TriangleAlert, type LucideIcon } from "lucide-react";
import { CopyId } from "@/components/cockpit/copy-id";
import { IconTile, type Tone } from "@/components/cockpit/icon-tile";
import { MetricCard, type MetricCardProps } from "@/components/cockpit/metric-card";
import { MetricGrid } from "@/components/cockpit/metric-grid";

interface DriverInfoTabProps {
  caseDetail: CaseDetailResponse;
  activeCase?: FraudCaseSummary;
  scorecard?: DriverScorecardResponse | null;
  scorecardError?: string | null;
}

export const HIGH_CANCELLATION_RATE = 5;
export const LOW_ACCEPTANCE_RATE = 85;
export const LOW_REPEAT_RISK = 40;
export const HIGH_REPEAT_RISK = 70;

const copy = {
  en: {
    driverRef: "Driver ID",
    title: "Driver information", name: "Name", plate: "Vehicle plate", vehicle: "Vehicle model", status: "Driver status",
    statement: "Driver statement", rating: "Average rating", ar: "Acceptance rate", cr: "Cancellation rate", trips: "Total trips",
    unavailable: "No data yet", history: "Driver history", loading: "Loading driver history…", error: "Driver history unavailable.",
    violation: "90-day violation ratio", fined: "Fined ratio", repeat: "Repeat-offense risk", benchmark: "Benchmark ratio", tenure: "Tenure",
    violationShort: "90d violations", finedShort: "Fined", repeatShort: "Repeat risk", benchmarkShort: "Benchmark", tenureShort: "Tenure",
    incidents: "Past incidents", date: "Date", finding: "Finding", outcome: "Outcome", code: "Error code", trip: "Trip ID", action: "Action taken",
    violationType: "Violation type", months: "months", emptyIncidents: "No past incidents recorded.",
    outcomes: { penalized: "Penalized", exonerated: "Exonerated", warned: "Warned", fine: "Fine", fined: "Fined", dismiss: "Dismissed", dismissed: "Dismissed", suspend: "Suspended", suspended: "Suspended" } as Record<string, string>,
  },
  vi: {
    driverRef: "Mã tài xế",
    title: "Thông tin tài xế", name: "Tên", plate: "Biển số", vehicle: "Mẫu xe", status: "Trạng thái tài xế",
    statement: "Giải trình tài xế", rating: "Điểm đánh giá trung bình", ar: "Tỷ lệ nhận chuyến", cr: "Tỷ lệ huỷ chuyến", trips: "Tổng số chuyến",
    unavailable: "Chưa có dữ liệu", history: "Lịch sử tài xế", loading: "Đang tải lịch sử tài xế…", error: "Không có lịch sử tài xế.",
    violation: "Tỷ lệ vi phạm 90 ngày", fined: "Tỷ lệ bị phạt", repeat: "Rủi ro tái phạm", benchmark: "Tỷ lệ chuẩn", tenure: "Thâm niên",
    violationShort: "Vi phạm 90 ngày", finedShort: "Bị phạt", repeatShort: "Rủi ro tái phạm", benchmarkShort: "Chuẩn", tenureShort: "Thâm niên",
    incidents: "Sự cố trước đây", date: "Ngày", finding: "Phát hiện", outcome: "Kết quả", code: "Mã lỗi", trip: "Mã chuyến đi", action: "Hành động",
    violationType: "Loại vi phạm", months: "tháng", emptyIncidents: "Chưa ghi nhận sự cố trước đây.",
    outcomes: { penalized: "Đã xử phạt", exonerated: "Đã minh oan", warned: "Đã cảnh cáo", fine: "Phạt tiền", fined: "Đã phạt tiền", dismiss: "Đã bác bỏ", dismissed: "Đã bác bỏ", suspend: "Đình chỉ", suspended: "Đình chỉ" } as Record<string, string>,
  },
} as const;

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function tripPercentage(value: unknown): number | null {
  const number = finiteNumber(value);
  return number === null ? null : number <= 1 ? number * 100 : number;
}

function initials(name: string): string {
  return name.trim().split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0]).join("").toUpperCase() || "?";
}

interface StatProps {
  label: string;
  title?: string;
  value: string | null;
  icon: LucideIcon;
  tone: Tone;
  severity?: MetricCardProps["severity"];
  children?: React.ReactNode;
}

function outcomeTone(status: string): string {
  if (["penalized", "fine", "fined", "warned"].includes(status)) return "border-gs-amber/30 bg-gs-amber-soft text-gs-amber-ink";
  if (["suspended", "suspend"].includes(status)) return "border-gs-red/30 bg-gs-red-soft text-gs-red";
  return "border-slate-200 bg-slate-100 text-slate-700";
}

export const DriverInfoTab: React.FC<DriverInfoTabProps> = ({ caseDetail, activeCase, scorecard: override, scorecardError }) => {
  const { locale } = useLocale();
  const t = copy[locale];
  const trip = caseDetail.trip;
  const record = caseDetail.case;
  const caseId = record?.id || activeCase?.id;
  const driverId = String(trip?.driver_id || "");
  const requestKey = `${caseId ?? ""}:${driverId}`;
  const [fetched, setFetched] = useState<{ key: string; history: DriverScorecardResponse | null; failed: boolean } | null>(null);

  useEffect(() => {
    if (override !== undefined) return;
    let cancelled = false;
    const request = caseId ? fetchCaseDriverScorecard(String(caseId)) : fetchDriverScorecard(driverId);
    request.then(history => {
      if (!cancelled) setFetched({ key: requestKey, history, failed: false });
    }).catch(() => {
      if (!cancelled) setFetched({ key: requestKey, history: null, failed: true });
    });
    return () => { cancelled = true; };
  }, [caseId, driverId, override, requestKey]);

  const current = fetched?.key === requestKey ? fetched : null;
  const history = override !== undefined ? override : current?.history;
  const loading = override === undefined && current === null;
  const error = scorecardError || (override === undefined && current?.failed ? t.error : null);
  const format = (value: number | null, suffix = "") => value === null
    ? null
    : `${value.toLocaleString(locale === "vi" ? "vi-VN" : "en-US", { maximumFractionDigits: 2 })}${suffix}`;
  const show = (value: unknown) => value == null || value === "" ? t.unavailable : String(value);
  const name = trip?.driver_name || activeCase?.driver_name || record?.driver_name;
  const plate = trip?.vehicle_plate || trip?.plate || activeCase?.vehicle_plate || record?.vehicle_plate;
  const vehicle = trip?.vehicle_model || trip?.vehicle_type;
  const status = String(trip?.driver_status || trip?.status || "unknown").toLowerCase();
  const statusTone = status === "suspended" ? "border-gs-red/30 bg-gs-red-soft text-gs-red"
    : status === "under_review" ? "border-gs-amber/30 bg-gs-amber-soft text-gs-amber-ink"
    : ["active", "completed"].includes(status) ? "border-gs-green/30 bg-gs-green-soft text-gs-green-ink"
    : "border-slate-200 bg-slate-100 text-slate-700";
  const rating = finiteNumber(trip?.rating);
  const acceptance = tripPercentage(trip?.acceptance_rate);
  const cancellation = tripPercentage(trip?.cancellation_rate);
  const trips = finiteNumber(trip?.total_trips);
  const stats: StatProps[] = [
    { label: t.rating, value: format(rating), icon: Star, tone: "warning" },
    { label: t.ar, value: format(acceptance, "%"), icon: CircleCheck, tone: "success", severity: acceptance !== null && acceptance < LOW_ACCEPTANCE_RATE ? "warning" : undefined },
    { label: t.cr, value: format(cancellation, "%"), icon: CircleX, tone: "danger", severity: cancellation !== null && cancellation > HIGH_CANCELLATION_RATE ? "danger" : undefined },
    { label: t.trips, value: format(trips), icon: Route, tone: "info" },
  ];
  const risk = finiteNumber(history?.repeat_offense_risk_score);
  const riskTone = risk !== null && risk < LOW_REPEAT_RISK ? "bg-gs-green" : risk !== null && risk < HIGH_REPEAT_RISK ? "bg-gs-amber" : "bg-gs-red";
  const historyStats: Array<StatProps & { raw: number | null; suffix: string }> = [
    { label: t.violationShort, title: t.violation, raw: finiteNumber(history?.violation_ratio_90d), suffix: "%", value: null, icon: TriangleAlert, tone: "warning" },
    { label: t.finedShort, title: t.fined, raw: finiteNumber(history?.fined_ratio), suffix: "%", value: null, icon: Receipt, tone: "violet" },
    { label: t.repeatShort, title: t.repeat, raw: risk, suffix: " / 100", value: null, icon: Crosshair, tone: "danger", severity: risk !== null && risk >= HIGH_REPEAT_RISK ? "danger" : undefined },
    { label: t.benchmarkShort, title: t.benchmark, raw: finiteNumber(history?.benchmark_violation_ratio), suffix: "%", value: null, icon: BarChart3, tone: "info" },
    { label: t.tenureShort, title: t.tenure, raw: finiteNumber(history?.tenure_months), suffix: ` ${t.months}`, value: null, icon: CalendarClock, tone: "success" },
  ];

  return (
    <div role="tabpanel" id="panel-driver" aria-labelledby="tab-driver" className="space-y-3 rounded-b-lg border-x border-b border-slate-200 bg-slate-50/60 px-2.5 pb-3 text-xs">
      <Card className="overflow-hidden">
        <CardHeader className="bg-gs-blue-soft/70 p-4">
          <h2 className="sr-only">{t.title}</h2>
          <div className="flex items-center gap-3">
            <Avatar className="size-12 bg-gs-blue-soft text-lg text-gs-blue" aria-hidden="true">
              <AvatarFallback>{initials(String(name || ""))}</AvatarFallback>
            </Avatar>
            <div className="min-w-0">
              <CardTitle title={t.name} className="break-words text-base font-semibold lg:text-lg">{show(name)}</CardTitle>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Badge variant="outline" className="bg-white font-mono text-xs" title={t.plate}>{show(plate)}</Badge>
                {trip?.driver_ref && <Badge variant="outline" className="bg-white font-mono text-xs" title={t.driverRef}>{String(trip.driver_ref)}</Badge>}
                <Badge variant="outline" className="bg-white/70 text-xs" title={t.vehicle}>{show(vehicle)}</Badge>
                <Badge variant="outline" className={cn("text-xs", statusTone)} title={t.status}>{workspaceState(status, locale)}</Badge>
              </div>
            </div>
          </div>
          <blockquote aria-label={t.statement} className="mt-3 flex gap-2 rounded-lg border border-gs-blue/30 bg-white/70 p-3 text-slate-700">
            <Quote aria-hidden="true" size={18} className="mt-0.5 block shrink-0 text-gs-blue" />
            <p className="min-w-0 whitespace-pre-wrap break-words text-sm italic leading-relaxed">{show(trip?.driver_statement)}</p>
          </blockquote>
        </CardHeader>
        <Separator />
        <CardContent className="bg-slate-50/50 p-3">
          <MetricGrid columns={4}>
            {stats.map(stat => <MetricCard key={stat.label} icon={stat.icon} tone={stat.tone} severity={stat.severity} label={stat.label} hint={stat.label} value={stat.value} />)}
          </MetricGrid>
        </CardContent>
      </Card>
      <Card className="overflow-hidden" role="region" aria-label={t.history}>
        <CardHeader className="border-b border-slate-200 bg-slate-100/80 p-3">
          <div className="flex items-center gap-2">
            <IconTile icon={History} tone="violet" />
            <CardTitle className="text-sm">{t.history}</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-3 p-3">
          {error ? <p role="alert" className="text-gs-red">{error}</p> : loading ? <p role="status" className="text-slate-500">{t.loading}</p> : (
            <>
              <MetricGrid>
                {historyStats.map(stat => (
                  <MetricCard key={stat.title} icon={stat.icon} tone={stat.tone} severity={stat.severity} label={stat.label} hint={stat.title} value={format(stat.raw, stat.suffix)}>
                    {stat.title === t.repeat && risk !== null && (
                      <Progress value={risk} aria-label={t.repeat} indicatorClassName={riskTone} className="mt-2 h-1.5 bg-slate-100" />
                    )}
                  </MetricCard>
                ))}
              </MetricGrid>
              <Separator />
              <section aria-label={t.incidents}>
                <h4 className="mb-2 text-sm font-semibold text-slate-900">{t.incidents}</h4>
                {history?.past_incidents?.length ? (
                  <div className="overflow-x-auto rounded-lg border border-slate-200">
                    <table className="w-full text-left text-xs">
                      <thead className="border-b border-slate-200 bg-slate-50 text-slate-600">
                        <tr>
                          <th scope="col" className="p-2 font-medium">{t.date}</th>
                          <th scope="col" className="p-2 font-medium">{t.finding}</th>
                          <th scope="col" className="p-2 font-medium">{t.outcome}</th>
                          <th scope="col" className="p-2 font-medium">{t.trip}</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {history.past_incidents.map((incident: DriverPastIncident & { error_code?: string }, index) => {
                          const date = new Date(incident.occurred_at);
                          const outcome = String(incident.status || "").toLowerCase();
                          const errorCode = incident.error_code || (/^ERR[-_]/i.test(incident.violation_type) ? incident.violation_type : null);
                          return (
                            <tr key={`${incident.trip_id}-${index}`} className="align-top hover:bg-slate-50/70">
                              <td className="whitespace-nowrap p-2 text-slate-600">
                                {Number.isNaN(date.getTime()) ? show(incident.occurred_at) : <time dateTime={incident.occurred_at} title={incident.occurred_at}>{date.toLocaleDateString(locale === "vi" ? "vi-VN" : "en-US")}</time>}
                              </td>
                              <td className="max-w-52 p-2">
                                <p className="truncate font-medium text-slate-800" title={incident.investigation_finding}>{show(incident.investigation_finding)}</p>
                                {incident.violation_type && incident.violation_type !== errorCode && (
                                  <p className="mt-1 truncate text-slate-600" title={`${t.violationType}: ${incident.violation_type}`}>{incident.violation_type}</p>
                                )}
                                {errorCode && <Badge variant="outline" className="mt-1 font-mono" title={t.code}>{errorCode}</Badge>}
                              </td>
                              <td className="max-w-40 p-2">
                                <Badge variant="outline" className={outcomeTone(outcome)} title={incident.status}>{t.outcomes[outcome] || show(incident.status)}</Badge>
                                {incident.action_taken && <p className="mt-1 break-words text-slate-600" title={`${t.action}: ${incident.action_taken}`}>{incident.action_taken}</p>}
                              </td>
                              <td className="p-2"><CopyId id={String(incident.trip_id)} label={t.trip} /></td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : <p className="text-slate-500">{history ? t.emptyIncidents : t.unavailable}</p>}
              </section>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
};
