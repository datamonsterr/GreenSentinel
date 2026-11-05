"use client";

import React, { useState, useEffect, useRef, useMemo } from "react";
import Link from "next/link";
import { isolatedGisBuild } from '@/lib/isolated-gis-build';
import { useAuth } from "@clerk/nextjs";
import {
  setTestApiTokenProvider,
  fetchTestCases,
  fetchTestSamples,
  fetchTestNotifications,
  fetchTestCaseDetail,
  triageCase,
  TestCase,
  TestSample,
  CaseFilters,
  TriageDecision,
  CaseStatus,
  TestNotification,
} from "@/lib/testApiClient";
import { WorkspaceInitSkeleton, CockpitDetailSkeleton } from "@/components/ui/skeleton";
import { OverviewTab } from "@/components/adjudication/overview-tab";
import { ConversationTab } from "@/components/adjudication/conversation-tab";
import { Activity, BellRing, CheckCircle2 } from "lucide-react";

function coordinateLocation(coordinates: unknown, label?: string) {
  if (!Array.isArray(coordinates) || coordinates.length < 2 || !coordinates.slice(0, 2).every(Number.isFinite)) return undefined;
  const [longitude, latitude] = coordinates;
  if (Math.abs(longitude) > 180 || Math.abs(latitude) > 90) return undefined;
  return { longitude, latitude, label };
}

// Inline SVG dual-axis telemetry chart — zero external dependencies
function TelemetryChart({ samples }: { samples: TestSample[] }) {
  if (samples.length === 0) return null;
  const W = 600, H = 200, PL = 48, PR = 48, PT = 12, PB = 28;
  const IW = W - PL - PR, IH = H - PT - PB;
  const maxSpeed = Math.max(...samples.map((s) => s.speed_mps), 1);
  const toX = (i: number) => PL + (i / (samples.length - 1 || 1)) * IW;
  const toY = (v: number, max: number) => PT + IH - (v / max) * IH;
  const speedPts = samples.map((s, i) => `${toX(i)},${toY(s.speed_mps, maxSpeed)}`).join(" ");
  const daviPts = samples.map((s, i) => `${toX(i)},${toY(Math.min(1, s.speed_mps / 30), 1)}`).join(" ");
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => ({ v: t * maxSpeed, y: toY(t * maxSpeed, maxSpeed) }));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full" preserveAspectRatio="none">
      {ticks.map((t) => (
        <g key={t.v}>
          <line x1={PL} y1={t.y} x2={W - PR} y2={t.y} stroke="#e2e8f0" strokeWidth="1" />
          <text x={PL - 4} y={t.y + 4} textAnchor="end" fontSize="9" fill="#94a3b8">{t.v.toFixed(1)}</text>
          <text x={W - PR + 4} y={t.y + 4} textAnchor="start" fontSize="9" fill="#f97316">{(t.v / maxSpeed).toFixed(2)}</text>
        </g>
      ))}
      <polyline points={speedPts} fill="none" stroke="#0ea5e9" strokeWidth="1.5" />
      <polyline points={daviPts} fill="none" stroke="#f97316" strokeWidth="1.5" />
      <text x={PL} y={H - 8} fontSize="9" fill="#0ea5e9">● Speed (m/s)</text>
      <text x={PL + 90} y={H - 8} fontSize="9" fill="#f97316">● DAVI (est.)</text>
      <text x={PL} y={PT - 2} fontSize="9" fill="#94a3b8">step_index: 0 … {samples.length - 1}</text>
    </svg>
  );
}

type TabType = "overview" | "conversation" | "chart" | "notifications";

export default function TestWorkplacePage() {
  const e2eAuthBypass = (process.env.NODE_ENV !== "production" || isolatedGisBuild()) && process.env.NEXT_PUBLIC_E2E_TEST === "true";
  // The E2E build omits ClerkProvider; the static env branch keeps production auth unchanged.
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const clerkAuth = e2eAuthBypass ? { getToken: async () => null, isLoaded: true } : useAuth();
  const getToken = e2eAuthBypass ? async () => null : clerkAuth.getToken;
  const isLoaded = e2eAuthBypass || clerkAuth.isLoaded;

  const [apiReady, setApiReady] = useState(false);
  const [filters, setFilters] = useState<Omit<CaseFilters, "status"> & { status: CaseStatus | "ALL" }>({ status: "ALL" });
  const [cases, setCases] = useState<TestCase[]>([]);
  const [selectedCase, setSelectedCase] = useState<TestCase | null>(null);
  const [caseDetail, setCaseDetail] = useState<any | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [samples, setSamples] = useState<TestSample[]>([]);
  const [notifications, setNotifications] = useState<TestNotification[]>([]);
  const [rationale, setRationale] = useState("");
  const [feedbackMessage, setFeedbackMessage] = useState<string | null>(null);
  const [appSwitcherOpen, setAppSwitcherOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<TabType>("overview");

  const getTokenRef = useRef(getToken);
  useEffect(() => {
    getTokenRef.current = getToken;
  });

  useEffect(() => {
    if (!isLoaded) return;
    setTestApiTokenProvider(() => getTokenRef.current());
    setApiReady(true);
    return () => {
      setTestApiTokenProvider(null);
      setApiReady(false);
    };
  }, [isLoaded]);

  useEffect(() => {
    if (!apiReady) return;

    const loadCases = async () => {
      try {
        const cleanFilters = { ...filters } as any;
        if (cleanFilters.status === "ALL") delete cleanFilters.status;
        const data = await fetchTestCases(cleanFilters);
        setCases(data);
        if (data.length > 0 && !selectedCase) {
          const urlCid =
            typeof window !== "undefined"
              ? new URLSearchParams(window.location.search).get("caseId") ||
                new URLSearchParams(window.location.search).get("case_id")
              : null;
          const matched = urlCid
            ? data.find((c) => c.id === urlCid || c.id === `case-sim-${urlCid}` || c.run_id === urlCid)
            : null;
          setSelectedCase(matched || data[0]);
        }
      } catch (err) {
        console.error("Failed to fetch test cases", err);
      }
    };

    loadCases();
    const interval = setInterval(loadCases, 10000);
    return () => clearInterval(interval);
  }, [apiReady, filters]);

  useEffect(() => {
    if (!selectedCase) {
      setCaseDetail(null);
      setSamples([]);
      setNotifications([]);
      return;
    }

    let isCurrent = true;
    setDetailLoading(true);
    setFeedbackMessage(null);

    fetchTestCaseDetail(selectedCase.id)
      .then((detail) => {
        if (!isCurrent) return;
        setCaseDetail(detail);
        if (detail.telemetry_samples && detail.telemetry_samples.length > 0) {
          setSamples(
            detail.telemetry_samples.map((s: any) => ({
              run_id: detail.case?.run_id || selectedCase.run_id || "",
              step_index: s.step_index ?? 0,
              latitude: s.position?.coordinates?.[1] ?? s.latitude ?? 21.0285,
              longitude: s.position?.coordinates?.[0] ?? s.longitude ?? 105.8524,
              speed_mps: s.speed_mps ?? 0,
              heading_deg: s.heading_deg ?? 0,
              is_fault_injected: Boolean(s.is_fault_injected),
              fault_type: s.fault_type ?? null,
              emitted_at: s.recorded_at ?? s.occurred_at ?? new Date().toISOString(),
            }))
          );
        } else if (selectedCase.run_id) {
          fetchTestSamples(selectedCase.run_id).then((sm) => {
            if (isCurrent) setSamples(sm);
          }).catch(() => {});
        }

        if (detail.notifications) {
          setNotifications(detail.notifications);
        } else if (selectedCase.run_id) {
          fetchTestNotifications(selectedCase.run_id).then((nt) => {
            if (isCurrent) setNotifications(nt);
          }).catch(() => {});
        }
      })
      .catch(async (err) => {
        console.warn("Detail fetch fallback to raw samples:", err);
        if (!isCurrent) return;
        let sampleData: TestSample[] = [];
        let notifData: TestNotification[] = [];
        if (selectedCase.run_id) {
          try {
            [sampleData, notifData] = await Promise.all([
              fetchTestSamples(selectedCase.run_id),
              fetchTestNotifications(selectedCase.run_id).catch(() => []),
            ]);
            if (isCurrent) {
              setSamples(sampleData);
              setNotifications(notifData);
            }
          } catch (e) {
            console.error("Failed to fetch fallback samples", e);
          }
        }
        if (isCurrent) {
          // Synthesize minimal caseDetail to ensure OverviewTab and evidence viewer render in sandbox test mode
          setCaseDetail({
            case: selectedCase,
            trip: {
              driver_name: "Nguyễn Văn Tài (Tài xế SM)",
              driver_status: "active",
              vehicle_plate: "29A-888.88",
              vehicle_type: "VinFast VF8",
              rating: 4.85,
              acceptance_rate: 92.5,
              cancellation_rate: 2.1,
              total_trips: 1240,
              pickup_address: "Điểm đón khách",
              dropoff_address: "Điểm trả khách",
              fare_amount_vnd: 85000,
            },
            assessment: {
              category: selectedCase.anomaly_types?.[0] || "JUMP",
              confidence: selectedCase.risk_score || 0.92,
              reason_codes: selectedCase.anomaly_types || ["JUMP"],
            },
            conversation: [],
            telemetry_samples: sampleData.map((s) => ({
              occurred_at: s.emitted_at,
              recorded_at: s.emitted_at,
              position: { coordinates: [s.longitude, s.latitude] },
              speed_mps: s.speed_mps,
              is_fault_injected: s.is_fault_injected,
              fault_type: s.fault_type,
            })),
            notifications: notifData,
          });
        }
      })
      .finally(() => {
        if (isCurrent) setDetailLoading(false);
      });

    return () => {
      isCurrent = false;
    };
  }, [selectedCase]);

  const handleTriageAction = async (decision: TriageDecision) => {
    if (!selectedCase) return;
    try {
      const res = await triageCase(selectedCase.id, { decision, rationale });
      setCases((prev) =>
        prev.map((c) => (c.id === selectedCase.id ? { ...c, status: res.new_status as CaseStatus } : c))
      );
      setSelectedCase((prev) => (prev ? { ...prev, status: res.new_status as CaseStatus } : prev));
      if (caseDetail) {
        setCaseDetail({
          ...caseDetail,
          case: {
            ...caseDetail.case,
            status: res.new_status,
          },
        });
      }
      setRationale("");
      setFeedbackMessage(`Đã xử lý hồ sơ thành công: ${decision}`);
      setTimeout(() => setFeedbackMessage(null), 4000);
    } catch (err) {
      console.error("Failed to triage", err);
      setFeedbackMessage(err instanceof Error ? err.message : "Thao tác xử lý thất bại");
    }
  };

  const mapTelemetry = useMemo(() => {
    return (caseDetail?.telemetry_samples ?? [])
      .filter((s: any) => coordinateLocation(s.position?.coordinates) && Number.isFinite(Date.parse(s.recorded_at ?? s.occurred_at)))
      .slice()
      .sort((a: any, b: any) => Date.parse(a.recorded_at ?? a.occurred_at) - Date.parse(b.recorded_at ?? b.occurred_at));
  }, [caseDetail?.telemetry_samples]);

  const initialDriverLocation = useMemo(() => {
    const coords =
      caseDetail?.trip?.initial_driver?.coordinates ??
      (caseDetail?.initial_driver && Number.isFinite(caseDetail.initial_driver.longitude) && Number.isFinite(caseDetail.initial_driver.latitude)
        ? [caseDetail.initial_driver.longitude, caseDetail.initial_driver.latitude]
        : mapTelemetry[0]?.position?.coordinates);
    return coordinateLocation(coords, caseDetail?.initial_driver?.label || "Start");
  }, [caseDetail, mapTelemetry]);

  const pickupLocation = useMemo(() => {
    const coords =
      caseDetail?.trip?.pickup?.coordinates ??
      (caseDetail?.pickup_location && Number.isFinite(caseDetail.pickup_location.longitude) && Number.isFinite(caseDetail.pickup_location.latitude)
        ? [caseDetail.pickup_location.longitude, caseDetail.pickup_location.latitude]
        : undefined);
    return coordinateLocation(coords, caseDetail?.trip?.pickup_address ?? caseDetail?.pickup_location?.label ?? "Điểm đón");
  }, [caseDetail]);

  const destinationLocation = useMemo(() => {
    const coords =
      caseDetail?.trip?.dropoff?.coordinates ??
      (caseDetail?.destination && Number.isFinite(caseDetail.destination.longitude) && Number.isFinite(caseDetail.destination.latitude)
        ? [caseDetail.destination.longitude, caseDetail.destination.latitude]
        : undefined);
    return coordinateLocation(coords, caseDetail?.trip?.dropoff_address ?? caseDetail?.destination?.label ?? "Điểm đến");
  }, [caseDetail]);

  if (!apiReady) return <WorkspaceInitSkeleton message="Opening test workplace…" />;

  return (
    <div className="flex-1 flex flex-col min-h-0 h-full overflow-hidden bg-background text-on-surface">
      {/* Top Application Sub-Header / Search & Tab Bar */}
      <div className="h-10 w-full bg-surface-container-lowest border-b border-outline-variant/60 flex items-center justify-between px-3 select-none shrink-0 z-30">
        <div className="flex items-center gap-2 relative">
          <div className="relative">
            <button
              onClick={() => setAppSwitcherOpen(!appSwitcherOpen)}
              className="w-7 h-7 rounded bg-emerald-600 hover:bg-emerald-700 active:bg-emerald-800 flex items-center justify-center text-white shadow-xs transition-colors cursor-pointer"
              aria-label="GreenSentinel app catalog"
              title="GreenSentinel app catalog"
              type="button"
            >
              <span className="material-symbols-outlined text-[16px]">security</span>
            </button>
            {appSwitcherOpen && (
              <div className="absolute left-0 top-9 w-64 bg-white border border-slate-200 rounded shadow-lg z-50 p-2 space-y-1">
                <div className="px-2 py-1 text-[10px] font-mono uppercase tracking-wider text-slate-400 font-semibold border-b border-slate-100 mb-1">
                  GreenSentinel Apps
                </div>
                <Link
                  href="/workplace"
                  className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs transition-colors text-left text-slate-700 hover:bg-slate-50"
                >
                  <span className="material-symbols-outlined text-[15px] text-emerald-600">gavel</span>
                  <span>Unified Adjudication (Production)</span>
                </Link>
                <Link
                  href="/test"
                  className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs transition-colors text-left text-slate-700 hover:bg-slate-50"
                >
                  <span className="material-symbols-outlined text-[15px] text-emerald-600">play_circle</span>
                  <span>Simulation Cockpit</span>
                </Link>
                <Link
                  href="/test/workplace"
                  className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs transition-colors text-left bg-emerald-50 text-emerald-800 font-semibold border border-emerald-200"
                >
                  <span className="material-symbols-outlined text-[15px] text-emerald-600">science</span>
                  <span>Test Workplace (Sandbox)</span>
                </Link>
              </div>
            )}
          </div>

          <div className="flex items-center gap-2">
            <span className="font-bold text-xs text-primary flex items-center gap-1">
              <span className="material-symbols-outlined text-[16px]">science</span>
              Test Workplace Sandbox
            </span>
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-amber-50 text-amber-800 border border-amber-200 font-semibold">
              SPEC-0130 §6.6
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Link
            href="/test"
            className="flex items-center gap-1 px-2.5 py-1 text-xs font-semibold rounded border border-outline-variant/60 bg-white hover:bg-slate-50 transition shadow-2xs"
          >
            <span className="material-symbols-outlined text-[14px]">arrow_back</span>
            <span>Back to Simulation</span>
          </Link>
        </div>
      </div>

      <div className="flex-1 flex min-h-0 overflow-hidden">
        {/* Left Panel: Queue */}
        <div className="w-[300px] shrink-0 border-r border-outline-variant/60 flex flex-col bg-surface-container-lowest">
          <div className="p-2.5 border-b border-outline-variant/60 flex flex-col gap-2 bg-white">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-slate-800 flex items-center gap-1">
                <span className="material-symbols-outlined text-[15px] text-primary">folder_open</span>
                Hồ sơ thử nghiệm ({cases.length})
              </span>
            </div>
            <select
              value={filters.status}
              onChange={(e) => setFilters({ ...filters, status: e.target.value as CaseStatus | "ALL" })}
              className="w-full h-7 px-2 text-xs rounded border border-outline-variant/60 bg-white focus:outline-none focus:border-primary"
            >
              <option value="ALL">ALL STATUSES</option>
              <option value="OPEN">OPEN</option>
              <option value="UNDER_REVIEW">UNDER REVIEW</option>
              <option value="CLOSED">CLOSED</option>
            </select>
            <div className="flex flex-wrap gap-1">
              {["JUMP", "OFFSET_NOISE", "DROPOUT", "DAVI_ANOMALY"].map((type) => {
                const isSelected = filters.anomaly_types?.includes(type);
                return (
                  <button
                    key={type}
                    onClick={() => {
                      const current = filters.anomaly_types || [];
                      const next = isSelected ? current.filter((t) => t !== type) : [...current, type];
                      setFilters({ ...filters, anomaly_types: next });
                    }}
                    className={`px-1.5 py-0.5 text-[9.5px] rounded border cursor-pointer font-medium transition ${
                      isSelected ? "bg-primary text-white border-primary" : "bg-surface border-outline-variant/60 text-secondary hover:bg-slate-50"
                    }`}
                  >
                    {type}
                  </button>
                );
              })}
            </div>
            <div className="flex flex-col gap-0.5">
              <div className="flex justify-between text-[10px] text-secondary">
                <span>Min Risk:</span>
                <span className="font-mono font-bold text-slate-800">{(filters.risk_score_min || 0).toFixed(1)}</span>
              </div>
              <input
                type="range"
                min="0"
                max="1"
                step="0.1"
                value={filters.risk_score_min || 0}
                onChange={(e) => setFilters({ ...filters, risk_score_min: parseFloat(e.target.value) })}
                className="w-full accent-primary h-1.5 cursor-pointer"
              />
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-2 space-y-1.5 bg-slate-50/50">
            {cases.length === 0 && (
              <div className="p-4 text-center text-xs text-slate-400 italic">
                Chưa có case mô phỏng nào. Hãy tạo và bấm &ldquo;Save Case&rdquo; trong Simulation Cockpit.
              </div>
            )}
            {cases.map((c) => (
              <button
                key={c.id}
                onClick={() => setSelectedCase(c)}
                className={`w-full text-left p-2.5 rounded-lg border shadow-2xs transition-all cursor-pointer ${
                  selectedCase?.id === c.id
                    ? "border-primary bg-primary/5 ring-1 ring-primary/20"
                    : "border-slate-200 bg-white hover:bg-slate-50"
                }`}
              >
                <div className="flex justify-between items-center mb-1">
                  <span className="font-mono text-xs font-bold text-slate-800 truncate max-w-[170px]">
                    {c.id}
                  </span>
                  <span
                    className={`text-[9px] px-1.5 py-0.2 rounded font-bold uppercase tracking-wider ${
                      c.status === "OPEN"
                        ? "bg-rose-100 text-rose-700 border border-rose-200"
                        : c.status === "UNDER_REVIEW"
                        ? "bg-amber-100 text-amber-700 border border-amber-200"
                        : "bg-emerald-100 text-emerald-700 border border-emerald-200"
                    }`}
                  >
                    {c.status}
                  </span>
                </div>
                <div className="flex items-center justify-between text-[10px] text-slate-500 mb-1">
                  <span>Risk Score:</span>
                  <span className="font-mono font-bold text-slate-700">{c.risk_score.toFixed(2)} ({(c.risk_score * 100).toFixed(0)}%)</span>
                </div>
                <div className="flex flex-wrap gap-1">
                  {c.anomaly_types.map((t) => (
                    <span key={t} className="text-[9px] bg-amber-50 text-amber-800 border border-amber-200 px-1 py-0.2 rounded font-mono">
                      {t}
                    </span>
                  ))}
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Right Area: Production-Grade Adjudication Workspace */}
        <div className="flex-1 flex flex-col min-w-0 bg-background overflow-hidden">
          {selectedCase ? (
            detailLoading && !caseDetail ? (
              <CockpitDetailSkeleton />
            ) : (
              <div className="flex-1 flex flex-col min-h-0 h-full overflow-hidden">
                {/* 1. Trip Profile & Driver Header (Identical to production /workplace) */}
                <div className="bg-white border-b border-slate-200 p-3 shadow-2xs space-y-2 shrink-0">
                  <div className="flex flex-col md:flex-row md:items-center justify-between gap-2.5">
                    {/* Driver Avatar + Identity */}
                    <div className="flex items-center gap-3 min-w-0">
                      <div className="relative shrink-0">
                        <img
                          src={
                            caseDetail?.trip?.driver_avatar_url ||
                            `https://api.dicebear.com/7.x/bottts/svg?seed=${encodeURIComponent(
                              caseDetail?.trip?.driver_name || "Driver"
                            )}`
                          }
                          alt={caseDetail?.trip?.driver_name || "Tài xế"}
                          className="w-10 h-10 rounded-full border border-slate-200 bg-slate-50 object-cover shadow-2xs"
                        />
                        <span
                          className={`absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-white ${
                            caseDetail?.trip?.driver_status === "suspended" ? "bg-rose-500" : "bg-emerald-500"
                          }`}
                          title={caseDetail?.trip?.driver_status === "suspended" ? "Đình chỉ" : "Hoạt động"}
                        />
                      </div>

                      <div className="min-w-0 space-y-0.5">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-bold text-slate-900 text-sm truncate">
                            {caseDetail?.trip?.driver_name || "Nguyễn Văn Tài (Tài xế SM)"}
                          </span>
                          <span className="font-mono font-semibold px-2 py-0.2 rounded bg-slate-100 border border-slate-300 text-slate-800 text-[11px] shrink-0 tracking-wider">
                            {caseDetail?.trip?.vehicle_plate || "29A-888.88"}
                          </span>
                        </div>

                        {/* Driver Metrics */}
                        <div className="flex items-center gap-1.5 flex-wrap text-[10.5px]">
                          <span className="inline-flex items-center gap-0.5 px-1.5 py-0.2 rounded bg-amber-50 border border-amber-200 text-amber-800 font-medium">
                            <span className="text-amber-500 text-[11px]">★</span>
                            <span>{caseDetail?.trip?.rating != null ? Number(caseDetail.trip.rating).toFixed(2) : "4.85"}</span>
                          </span>
                          <span className="px-1.5 py-0.2 rounded bg-emerald-50 border border-emerald-200 text-emerald-800 font-medium">
                            {caseDetail?.trip?.acceptance_rate != null ? Number(caseDetail.trip.acceptance_rate).toFixed(1) : "92.5"}% Nhận
                          </span>
                          <span className="px-1.5 py-0.2 rounded bg-slate-100 border border-slate-200 text-slate-700">
                            {caseDetail?.trip?.cancellation_rate != null ? Number(caseDetail.trip.cancellation_rate).toFixed(1) : "2.1"}% Hủy
                          </span>
                          <span className="px-1.5 py-0.2 rounded bg-slate-50 border border-slate-200 text-slate-600 hidden sm:inline-block">
                            {caseDetail?.trip?.total_trips != null ? Number(caseDetail.trip.total_trips).toLocaleString() : "1,240"} chuyến
                          </span>
                          <span className="px-1.5 py-0.2 rounded bg-slate-50 border border-slate-200 text-slate-600 hidden md:inline-block">
                            {caseDetail?.trip?.vehicle_type || "VinFast VF8"}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Status Badges & Pricing */}
                    <div className="flex items-center gap-2 shrink-0 flex-wrap">
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10.5px] font-semibold border bg-emerald-50 text-emerald-700 border-emerald-200">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                        <span>{caseDetail?.trip?.status || "Completed"}</span>
                      </span>

                      <span className="inline-flex items-center px-2 py-0.5 rounded text-[10.5px] font-semibold uppercase tracking-wider border bg-purple-50 text-purple-700 border-purple-200">
                        Match: {caseDetail?.trip?.match_type || "auto"}
                      </span>

                      <div className="font-bold text-slate-900 text-xs px-2 py-0.5 rounded bg-slate-50 border border-slate-200">
                        {caseDetail?.trip?.fare_amount_vnd != null
                          ? `${Number(caseDetail.trip.fare_amount_vnd).toLocaleString("vi-VN")} ₫`
                          : "85.000 ₫"}
                      </div>
                    </div>
                  </div>

                  {/* Pickup -> Destination row */}
                  <div className="flex items-center gap-1.5 text-slate-700 text-xs pt-1 border-t border-slate-100 font-medium">
                    <span className="w-2 h-2 rounded-full bg-emerald-500 shrink-0" title="Điểm đón" />
                    <span className="truncate max-w-[260px] text-slate-900 font-semibold" title={caseDetail?.trip?.pickup_address}>
                      {caseDetail?.trip?.pickup_address || "Điểm đón khách"}
                    </span>
                    <span className="text-slate-400 shrink-0 px-1">→</span>
                    <span className="w-2 h-2 rounded-full bg-rose-500 shrink-0" title="Điểm đến" />
                    <span className="truncate max-w-[260px] text-slate-900 font-semibold" title={caseDetail?.trip?.dropoff_address}>
                      {caseDetail?.trip?.dropoff_address || "Điểm trả khách"}
                    </span>
                  </div>

                  {/* AI Advisory Anomaly Assessment Banner */}
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pt-1.5 border-t border-slate-100 bg-slate-50/80 -mx-3 -mb-3 px-3 py-1.5 rounded-b">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold text-slate-800 text-[11px] inline-flex items-center gap-1.5">
                        <span className="w-2 h-2 rounded-full bg-emerald-600 animate-pulse" />
                        AI Assessment:
                      </span>
                      <span className="inline-flex items-center px-2 py-0.2 rounded font-mono font-bold text-xs bg-emerald-50 text-emerald-800 border border-emerald-300">
                        {caseDetail?.assessment?.category || selectedCase.anomaly_types?.[0] || "NORMAL_TRIP"} (
                        {caseDetail?.assessment?.confidence != null
                          ? Math.round(caseDetail.assessment.confidence * 100)
                          : Math.round(selectedCase.risk_score * 100)}
                        %)
                      </span>
                      <span className="px-1.5 py-0.2 rounded text-[10px] font-semibold border bg-blue-50 text-blue-700 border-blue-200">
                        Priority: {caseDetail?.case?.priority || "P1"}
                      </span>
                    </div>
                    {caseDetail?.assessment?.reason_codes && (
                      <div className="flex items-center gap-1 overflow-x-auto text-[10px] text-slate-500">
                        <span className="text-slate-400">Signals:</span>
                        {caseDetail.assessment.reason_codes.slice(0, 3).map((code: string) => (
                          <span key={code} className="px-1.5 py-0.2 rounded bg-white border border-slate-200 text-slate-600 font-mono">
                            {code}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                {/* 2. Center Tabs Bar */}
                <div className="h-9 bg-slate-100 border-b border-slate-200 flex items-center justify-between px-3 shrink-0">
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => setActiveTab("overview")}
                      aria-label="Map"
                      className={`px-3 py-1 text-xs font-medium rounded transition flex items-center gap-1.5 cursor-pointer ${
                        activeTab === "overview"
                          ? "bg-white text-slate-900 shadow-2xs font-semibold"
                          : "text-slate-600 hover:text-slate-900 hover:bg-slate-200/50"
                      }`}
                    >
                      <span className="material-symbols-outlined text-[15px]">dashboard</span>
                      <span>Overview</span>
                      <span className="sr-only">Map</span>
                    </button>
                    <button
                      onClick={() => setActiveTab("conversation")}
                      className={`px-3 py-1 text-xs font-medium rounded transition flex items-center gap-1.5 cursor-pointer ${
                        activeTab === "conversation"
                          ? "bg-white text-slate-900 shadow-2xs font-semibold"
                          : "text-slate-600 hover:text-slate-900 hover:bg-slate-200/50"
                      }`}
                    >
                      <span className="material-symbols-outlined text-[15px]">forum</span>
                      <span>Conversation</span>
                      {(caseDetail?.conversation?.length || 0) > 0 && (
                        <span className="px-1.5 py-0.2 text-[9px] bg-slate-200 text-slate-700 rounded-full font-bold">
                          {caseDetail.conversation.length}
                        </span>
                      )}
                    </button>
                    <button
                      onClick={() => setActiveTab("chart")}
                      aria-label="Chart"
                      className={`px-3 py-1 text-xs font-medium rounded transition flex items-center gap-1.5 cursor-pointer ${
                        activeTab === "chart"
                          ? "bg-white text-slate-900 shadow-2xs font-semibold"
                          : "text-slate-600 hover:text-slate-900 hover:bg-slate-200/50"
                      }`}
                    >
                      <span className="material-symbols-outlined text-[15px]">monitoring</span>
                      <span>Chart</span>
                    </button>
                    <button
                      onClick={() => setActiveTab("notifications")}
                      className={`px-3 py-1 text-xs font-medium rounded transition flex items-center gap-1.5 cursor-pointer ${
                        activeTab === "notifications"
                          ? "bg-white text-slate-900 shadow-2xs font-semibold"
                          : "text-slate-600 hover:text-slate-900 hover:bg-slate-200/50"
                      }`}
                    >
                      <span className="material-symbols-outlined text-[15px]">notifications</span>
                      <span>Sandbox Alerts</span>
                      {notifications.length > 0 && (
                        <span className="px-1.5 py-0.2 text-[9px] bg-amber-200 text-amber-900 rounded-full font-bold">
                          {notifications.length}
                        </span>
                      )}
                    </button>
                  </div>
                </div>

                {/* 3. Main Center Tab Content */}
                <div className="flex-1 overflow-y-auto min-h-0 bg-slate-50">
                  {caseDetail && (
                    <div className={activeTab === "overview" ? "block space-y-4" : "hidden"}>
                      <OverviewTab
                        caseDetail={caseDetail}
                        selectedCaseId={selectedCase.id}
                        pickupLocation={pickupLocation}
                        initialDriverLocation={initialDriverLocation}
                        destinationLocation={destinationLocation}
                        mapTelemetry={mapTelemetry}
                        isActive={activeTab === "overview"}
                      />

                      {/* Evidence Viewer / Sandbox Notifications in Overview */}
                      <div className="p-4 pt-0">
                        <div className="bg-white p-4 rounded-lg border border-slate-200 shadow-xs space-y-3">
                          <div className="flex items-center justify-between border-b pb-2">
                            <span className="text-xs font-bold text-slate-800 flex items-center gap-1.5">
                              <BellRing className="w-4 h-4 text-amber-600" />
                              Intercepted Sandbox Notifications ({notifications.length})
                            </span>
                          </div>
                          <div className="space-y-2">
                            {notifications.map((notif: TestNotification, idx: number) => (
                              <div key={idx} className="p-3 rounded-lg bg-slate-50 border border-slate-200 text-xs flex flex-col gap-1">
                                <div className="flex items-center justify-between text-[11px] font-mono text-slate-500">
                                  <span className="px-1.5 py-0.2 rounded bg-emerald-100 text-emerald-800 font-bold">
                                    {notif.channel}
                                  </span>
                                  <span>To: {notif.recipient_id} ({notif.recipient_type})</span>
                                </div>
                                <p className="text-slate-800 text-xs mt-1">{notif.body}</p>
                              </div>
                            ))}
                            {notifications.length === 0 && (
                              <div className="text-xs text-slate-400 italic py-4 text-center">
                                Không có thông báo sandbox nào được chặn trong chuyến này.
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {caseDetail && (
                    <div className={activeTab === "conversation" ? "block p-3" : "hidden"}>
                      <ConversationTab
                        caseDetail={caseDetail}
                        activeCaseDriverName={caseDetail?.trip?.driver_name || "Nguyễn Văn Tài"}
                      />
                    </div>
                  )}

                  <div className={activeTab === "chart" ? "block p-4" : "hidden"}>
                    <div className="bg-white p-4 rounded-lg border border-slate-200 shadow-xs space-y-2">
                      <div className="flex items-center justify-between border-b pb-2">
                        <span className="text-xs font-bold text-slate-800">
                          Dual-Axis Kinematics &amp; DAVI Drift Chart ({samples.length} mẫu)
                        </span>
                        <span className="text-[10px] text-slate-500 font-mono">
                          X: Step Index · Y: Vận tốc (m/s) &amp; DAVI Anomaly Score
                        </span>
                      </div>
                      <div className="w-full h-80">
                        <TelemetryChart samples={samples} />
                      </div>
                    </div>
                  </div>

                  {activeTab === "notifications" && (
                    <div className="block p-4">
                      <div className="bg-white p-4 rounded-lg border border-slate-200 shadow-xs space-y-3">
                        <div className="flex items-center justify-between border-b pb-2">
                          <span className="text-xs font-bold text-slate-800 flex items-center gap-1.5">
                            <BellRing className="w-4 h-4 text-amber-600" />
                            Sandbox Alerts Feed ({notifications.length})
                          </span>
                        </div>
                        <div className="space-y-2">
                          {notifications.map((notif: TestNotification, idx: number) => (
                            <div key={idx} className="p-3 rounded-lg bg-slate-50 border border-slate-200 text-xs flex flex-col gap-1">
                              <div className="flex items-center justify-between text-[11px] font-mono text-slate-500">
                                <span className="px-1.5 py-0.2 rounded bg-emerald-100 text-emerald-800 font-bold">
                                  {notif.channel}
                                </span>
                                <span>To: {notif.recipient_id} ({notif.recipient_type})</span>
                              </div>
                              <p className="text-slate-800 text-xs mt-1">{notif.body}</p>
                            </div>
                          ))}
                          {notifications.length === 0 && (
                            <div className="text-xs text-slate-400 italic py-4 text-center">
                              Không có thông báo sandbox nào được chặn trong chuyến này.
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                {/* 4. Bottom Triage Action Bar */}
                <div className="p-3 bg-white border-t border-slate-200 flex flex-col sm:flex-row items-center justify-between gap-3 shadow-xs shrink-0">
                  <div className="flex-1 w-full max-w-lg flex items-center gap-2">
                    <span className="text-xs font-bold text-slate-700 shrink-0">Ghi chú:</span>
                    <input
                      type="text"
                      value={rationale}
                      onChange={(e) => setRationale(e.target.value)}
                      placeholder="Enter rationale for audit log / Nhập lý do đối soát..."
                      className="w-full h-8 px-2.5 text-xs bg-slate-50 rounded border border-slate-300 focus:border-primary focus:bg-white focus:outline-none"
                    />
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    {feedbackMessage && (
                      <span className="text-xs font-semibold text-emerald-700 animate-fade-in mr-2">
                        {feedbackMessage}
                      </span>
                    )}
                    <button
                      onClick={() => handleTriageAction("APPROVE_LEGITIMATE")}
                      className="px-3.5 py-1.5 text-xs font-semibold rounded bg-emerald-600 text-white hover:bg-emerald-700 flex items-center gap-1.5 shadow-2xs cursor-pointer transition"
                    >
                      <CheckCircle2 className="w-3.5 h-3.5" /> Approve
                    </button>
                    <button
                      onClick={() => handleTriageAction("INVESTIGATE")}
                      className="px-3.5 py-1.5 text-xs font-semibold rounded bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-300 cursor-pointer transition"
                    >
                      Investigate
                    </button>
                  </div>
                </div>
              </div>
            )
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-secondary h-full gap-4">
              <Activity className="w-12 h-12 opacity-20" />
              <p>Select a case from the queue to begin triage.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
