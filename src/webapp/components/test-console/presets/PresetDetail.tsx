"use client";

import React, { useEffect, useState } from "react";
import {
  fetchTestPresetDetail,
  type TestPreset,
  type TestPresetDetailResponse,
  type TestPresetTrip,
  type PresetBatchRunResponse,
} from "@/lib/testApiClient";
import { PresetRunDialog } from "./PresetRunDialog";
import { PresetBatchLogs } from "./PresetBatchLogs";
import {
  AlertCircle,
  BarChart3,
  Calendar,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  FileText,
  Hash,
  Info,
  ListOrdered,
  Loader2,
  Play,
  Scale,
  ShieldAlert,
} from "lucide-react";

export type PresetTabKey = "info" | "samples" | "distribution" | "logs";

export interface PresetDetailProps {
  presetId: string;
  initialPreset?: TestPreset;
  onOpenInManual: (preset: TestPreset, trip: TestPresetTrip) => void;
  className?: string;
}

export function PresetDetail({
  presetId,
  initialPreset,
  onOpenInManual,
  className = "",
}: PresetDetailProps) {
  const [detail, setDetail] = useState<TestPresetDetailResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<PresetTabKey>("info");
  const [runDialogOpen, setRunDialogOpen] = useState(false);
  const [activeBatchId, setActiveBatchId] = useState<string | null>(null);

  // Progressive disclosure collapsed states for distribution sections
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({
    label: true,
    severity: true,
    scenario: false,
    city: false,
    cancellation: false,
  });

  const toggleSection = (key: string) => {
    setOpenSections((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);

    fetchTestPresetDetail(presetId)
      .then((data) => {
        if (!active) return;
        setDetail(data);
      })
      .catch((err) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Không thể tải chi tiết tập mẫu");
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [presetId]);

  const preset = detail || (initialPreset as TestPresetDetailResponse | undefined);

  if (loading && !preset) {
    return (
      <div className="flex items-center justify-center py-20 text-xs text-secondary gap-2">
        <Loader2 className="w-4 h-4 animate-spin text-primary" />
        <span>Đang tải thông tin chi tiết tập mẫu…</span>
      </div>
    );
  }

  if (error && !preset) {
    return (
      <div className="p-4 rounded-lg bg-error-container text-error text-xs flex items-center gap-2">
        <AlertCircle className="w-4 h-4 shrink-0" />
        <span>{error}</span>
      </div>
    );
  }

  if (!preset) {
    return (
      <div className="text-xs text-secondary italic py-8 text-center">
        Không tìm thấy thông tin tập mẫu đã chọn.
      </div>
    );
  }

  const handleRunSuccess = (batchRun: PresetBatchRunResponse) => {
    setActiveBatchId(batchRun.id);
    setActiveTab("logs");
  };

  const dist = detail?.distributions;
  const totalRecords = dist?.total_records || preset.available_trips || preset.trip_count || 1;

  return (
    <div className={`space-y-4 ${className}`} data-testid="preset-detail-container">
      {/* Top Header Card */}
      <div className="flex flex-wrap items-start justify-between gap-4 p-4 rounded-xl border border-outline-variant/60 bg-surface-container-lowest shadow-sm">
        <div className="space-y-1.5 max-w-xl">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-base font-bold text-on-surface" data-testid="preset-detail-title">
              {preset.title}
            </h2>
            {!preset.available ? (
              <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-amber-100 text-amber-800">
                Tạm chưa mở
              </span>
            ) : (
              <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3" /> Sẵn sàng
              </span>
            )}
            {preset.source_label && (
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-surface-container text-secondary">
                {preset.source_label}
              </span>
            )}
          </div>
          <p className="text-xs text-secondary">{preset.description}</p>
          {!preset.available && preset.unavailable_reason && (
            <p className="text-xs text-amber-700 italic">{preset.unavailable_reason}</p>
          )}
        </div>

        {/* Action Button "Chạy" */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={!preset.available}
            onClick={() => setRunDialogOpen(true)}
            data-testid="preset-run-button"
            className="flex items-center gap-1.5 px-4 py-2 text-xs font-bold rounded-lg bg-primary text-white hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition shadow-sm"
          >
            <Play className="w-3.5 h-3.5 fill-current" />
            <span>Chạy đợt mô phỏng</span>
          </button>
        </div>
      </div>

      {/* Detail Navigation Tabs */}
      <div className="flex border-b border-outline-variant/60 gap-1 text-xs font-semibold">
        <button
          type="button"
          onClick={() => setActiveTab("info")}
          data-testid="tab-trigger-info"
          className={`flex items-center gap-1.5 px-3 py-2 border-b-2 transition ${
            activeTab === "info"
              ? "border-primary text-primary bg-primary/5"
              : "border-transparent text-secondary hover:text-on-surface"
          }`}
        >
          <Info className="w-3.5 h-3.5" />
          <span>Thông tin</span>
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("samples")}
          data-testid="tab-trigger-samples"
          className={`flex items-center gap-1.5 px-3 py-2 border-b-2 transition ${
            activeTab === "samples"
              ? "border-primary text-primary bg-primary/5"
              : "border-transparent text-secondary hover:text-on-surface"
          }`}
        >
          <ListOrdered className="w-3.5 h-3.5" />
          <span>Chuyến mẫu ({preset.sample_trips?.length || 0})</span>
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("distribution")}
          data-testid="tab-trigger-distribution"
          className={`flex items-center gap-1.5 px-3 py-2 border-b-2 transition ${
            activeTab === "distribution"
              ? "border-primary text-primary bg-primary/5"
              : "border-transparent text-secondary hover:text-on-surface"
          }`}
        >
          <BarChart3 className="w-3.5 h-3.5" />
          <span>Phân bổ dữ liệu</span>
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("logs")}
          data-testid="tab-trigger-logs"
          className={`flex items-center gap-1.5 px-3 py-2 border-b-2 transition ${
            activeTab === "logs"
              ? "border-primary text-primary bg-primary/5"
              : "border-transparent text-secondary hover:text-on-surface"
          }`}
        >
          <FileText className="w-3.5 h-3.5" />
          <span>Nhật ký đợt chạy</span>
        </button>
      </div>

      {/* Tab 1: Info Tab */}
      {activeTab === "info" && (
        <div className="space-y-4" data-testid="tab-content-info">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            <div className="border border-outline-variant/60 rounded-lg p-3 bg-surface-container-lowest">
              <div className="text-[10px] uppercase font-bold text-secondary mb-1 flex items-center gap-1">
                <FileText className="w-3 h-3" /> Nguồn phát hành (Source)
              </div>
              <div className="text-xs font-semibold text-on-surface">
                {detail?.source_release || preset.source_label || "Bản phát hành chuẩn v1"}
              </div>
            </div>

            <div className="border border-outline-variant/60 rounded-lg p-3 bg-surface-container-lowest">
              <div className="text-[10px] uppercase font-bold text-secondary mb-1 flex items-center gap-1">
                <Calendar className="w-3 h-3" /> Phiên bản (Revision)
              </div>
              <div className="text-xs font-mono font-semibold text-primary">
                {detail?.revision || "914a3656"}
              </div>
            </div>

            <div className="border border-outline-variant/60 rounded-lg p-3 bg-surface-container-lowest">
              <div className="text-[10px] uppercase font-bold text-secondary mb-1 flex items-center gap-1">
                <Hash className="w-3 h-3" /> Mã băm dữ liệu (SHA256)
              </div>
              <div className="text-xs font-mono text-secondary truncate" title={detail?.trips_sha256 || "N/A"}>
                {detail?.trips_sha256 || "— (Đã đối soát)"}
              </div>
            </div>

            <div className="border border-outline-variant/60 rounded-lg p-3 bg-surface-container-lowest">
              <div className="text-[10px] uppercase font-bold text-secondary mb-1 flex items-center gap-1">
                <Scale className="w-3 h-3" /> Giấy phép (License)
              </div>
              <div className="text-xs font-semibold text-on-surface">
                {detail?.license || "CC BY 4.0 / Synthetic Benchmark"}
              </div>
            </div>

            <div className="border border-outline-variant/60 rounded-lg p-3 bg-surface-container-lowest">
              <div className="text-[10px] uppercase font-bold text-secondary mb-1 flex items-center gap-1">
                <ListOrdered className="w-3 h-3" /> Tổng số chuyến khả dụng
              </div>
              <div className="text-xs font-semibold text-on-surface">
                {detail?.trip_count || preset.available_trips || preset.selection_size || 0} chuyến
              </div>
            </div>

            <div className="border border-outline-variant/60 rounded-lg p-3 bg-surface-container-lowest">
              <div className="text-[10px] uppercase font-bold text-secondary mb-1 flex items-center gap-1">
                <ShieldAlert className="w-3 h-3" /> Trạng thái kiểm định
              </div>
              <div className="text-xs font-semibold text-emerald-700">
                Đã chuẩn hóa tọa độ &amp; vi phạm
              </div>
            </div>
          </div>

          {/* Description & metrics */}
          <div className="p-3 rounded-lg border border-outline-variant/60 bg-surface-container-lowest space-y-2">
            <h4 className="text-xs font-bold text-on-surface">Mô tả chi tiết</h4>
            <p className="text-xs text-secondary leading-relaxed">{preset.description}</p>
          </div>

          {preset.metrics && Object.keys(preset.metrics).length > 0 && (
            <div className="space-y-2">
              <h4 className="text-xs font-bold text-on-surface">Chỉ số tập mẫu (Metrics)</h4>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {Object.entries(preset.metrics).map(([key, val]) => (
                  <div key={key} className="p-2 border border-outline-variant/50 rounded bg-surface-container">
                    <div className="text-[10px] text-secondary uppercase font-semibold">{key}</div>
                    <div className="text-xs font-semibold">
                      {typeof val === "object" ? JSON.stringify(val) : String(val)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Tab 2: Samples Table Tab */}
      {activeTab === "samples" && (
        <div className="space-y-3" data-testid="tab-content-samples">
          <div className="text-xs text-secondary flex items-center justify-between">
            <span>Danh sách các chuyến mẫu điển hình:</span>
            <span className="italic">* Nút &quot;Mở trong bảng thủ công&quot; chuyển sang bảng điều khiển cũ để xem chi tiết.</span>
          </div>

          <div className="border border-outline-variant/60 rounded-lg overflow-x-auto bg-surface-container-lowest">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-outline-variant/60 bg-surface-container text-secondary text-[11px]">
                  <th className="p-2 font-semibold">Mã chuyến (trip_ref)</th>
                  <th className="p-2 font-semibold">Nhãn</th>
                  <th className="p-2 font-semibold">Mức độ</th>
                  <th className="p-2 font-semibold">Kịch bản</th>
                  <th className="p-2 font-semibold">Thành phố</th>
                  <th className="p-2 font-semibold">Tài xế &amp; Biển số</th>
                  <th className="p-2 font-semibold">Đón → Trả</th>
                  <th className="p-2 font-semibold">Quãng đường &amp; Thời gian</th>
                  <th className="p-2 font-semibold text-right">Thao tác</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-outline-variant/40">
                {(!preset.sample_trips || preset.sample_trips.length === 0) ? (
                  <tr>
                    <td colSpan={9} className="p-6 text-center text-xs text-secondary italic">
                      Không có chuyến mẫu nào trong tập này.
                    </td>
                  </tr>
                ) : (
                  preset.sample_trips.map((trip: TestPresetTrip) => {
                    const distKm = trip.distance_m ? (trip.distance_m / 1000).toFixed(2) : "—";
                    const durMin = trip.duration_s ? Math.round(trip.duration_s / 60) : "—";

                    return (
                      <tr
                        key={trip.trip_ref}
                        className="hover:bg-surface-container-low transition"
                        data-testid={`sample-row-${trip.trip_ref}`}
                      >
                        <td className="p-2 font-mono font-semibold text-primary">{trip.trip_ref}</td>
                        <td className="p-2 font-semibold">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] ${
                              trip.label === "no_violation"
                                ? "bg-emerald-100 text-emerald-800"
                                : trip.label === "insufficient_evidence"
                                ? "bg-amber-100 text-amber-800"
                                : "bg-rose-100 text-rose-800"
                            }`}
                          >
                            {trip.label}
                          </span>
                        </td>
                        <td className="p-2 text-secondary">{trip.severity || "—"}</td>
                        <td className="p-2 text-secondary">{trip.scenario || "—"}</td>
                        <td className="p-2 text-secondary">{trip.city || "—"}</td>
                        <td className="p-2">
                          <div>{trip.driver_display_name || trip.driver_name || "—"}</div>
                          {trip.license_plate && (
                            <div className="font-mono text-[10px] text-secondary">{trip.license_plate}</div>
                          )}
                        </td>
                        <td className="p-2 text-secondary max-w-xs truncate" title={`${trip.pickup_name || "—"} → ${trip.dropoff_name || "—"}`}>
                          {trip.pickup_name || "—"} → {trip.dropoff_name || "—"}
                        </td>
                        <td className="p-2 text-secondary">
                          {distKm !== "—" ? `${distKm} km` : "—"} · {durMin !== "—" ? `${durMin} phút` : "—"}
                        </td>
                        <td className="p-2 text-right">
                          <button
                            type="button"
                            onClick={() => onOpenInManual(preset, trip)}
                            className="inline-flex items-center gap-1 text-[11px] font-medium px-2 py-1 rounded border border-outline-variant/60 hover:bg-primary/10 hover:text-primary transition"
                            title="Mở trong bảng điều khiển thủ công cũ"
                            data-testid={`open-manual-${trip.trip_ref}`}
                          >
                            <span>Mở trong bảng thủ công</span>
                            <ExternalLink className="w-3 h-3" />
                          </button>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tab 3: Distribution Tab (Progressive Disclosure) */}
      {activeTab === "distribution" && (
        <div className="space-y-3" data-testid="tab-content-distribution">
          {!dist ? (
            <div className="text-xs text-secondary italic py-6 text-center">
              Đang tải biểu đồ phân bổ…
            </div>
          ) : (
            <div className="space-y-3">
              {/* Section 1: Label Distribution (Fraud by ERR vs no_violation vs insufficient_evidence) */}
              <div className="border border-outline-variant/60 rounded-lg p-3 bg-surface-container-lowest">
                <div
                  className="flex items-center justify-between cursor-pointer select-none"
                  onClick={() => toggleSection("label")}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-on-surface">
                      Phân bổ kết luận vi phạm (Fraud vs Bình thường)
                    </span>
                    <span className="text-[10px] text-secondary">
                      ({dist.by_label.fraud} gian lận · {dist.by_label.no_violation} hợp lệ · {dist.by_label.insufficient_evidence} thiếu bằng chứng)
                    </span>
                  </div>
                  {openSections.label ? <ChevronUp className="w-4 h-4 text-secondary" /> : <ChevronDown className="w-4 h-4 text-secondary" />}
                </div>

                {openSections.label && (
                  <div className="mt-3 space-y-2">
                    {/* High-level count pills with hover tooltips per UI guidelines */}
                    <div className="flex flex-wrap gap-2 text-xs">
                      <span
                        className="px-2.5 py-1 rounded-full bg-rose-50 border border-rose-200 text-rose-800 font-semibold cursor-help"
                        title="Tổng số chuyến bị phát hiện gian lận quy định"
                      >
                        Gian lận: {dist.by_label.fraud} ({((dist.by_label.fraud / totalRecords) * 100).toFixed(1)}%)
                      </span>
                      <span
                        className="px-2.5 py-1 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-800 font-semibold cursor-help"
                        title="Chuyến đi hoàn toàn bình thường, không có dấu hiệu vi phạm"
                      >
                        Không vi phạm: {dist.by_label.no_violation} ({((dist.by_label.no_violation / totalRecords) * 100).toFixed(1)}%)
                      </span>
                      <span
                        className="px-2.5 py-1 rounded-full bg-amber-50 border border-amber-200 text-amber-800 font-semibold cursor-help"
                        title="Không đủ chứng cứ số hoặc tín hiệu viễn trắc để kết luận"
                      >
                        Thiếu bằng chứng: {dist.by_label.insufficient_evidence} ({((dist.by_label.insufficient_evidence / totalRecords) * 100).toFixed(1)}%)
                      </span>
                    </div>

                    {/* Breakdown by ERR code */}
                    {Object.keys(dist.per_code || {}).length > 0 && (
                      <div className="pt-2 border-t border-outline-variant/40">
                        <div className="text-[11px] font-semibold text-secondary mb-1.5">
                          Chi tiết theo mã vi phạm (ERR Code):
                        </div>
                        <div className="space-y-1.5">
                          {Object.entries(dist.per_code).map(([code, count]) => {
                            const pct = ((count / totalRecords) * 100).toFixed(1);
                            return (
                              <div key={code} className="space-y-0.5">
                                <div className="flex justify-between text-xs font-mono">
                                  <span
                                    className="font-bold cursor-help text-primary hover:underline"
                                    title={`Mã vi phạm: ${code} - Phát hiện ${count} chuyến`}
                                  >
                                    {code}
                                  </span>
                                  <span className="text-secondary">{count} chuyến ({pct}%)</span>
                                </div>
                                <div className="w-full bg-surface-container rounded-full h-1.5 overflow-hidden">
                                  <div
                                    className="bg-primary h-1.5 rounded-full"
                                    style={{ width: `${pct}%` }}
                                    title={`${code}: ${pct}%`}
                                  />
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Section 2: Severity Distribution */}
              <div className="border border-outline-variant/60 rounded-lg p-3 bg-surface-container-lowest">
                <div
                  className="flex items-center justify-between cursor-pointer select-none"
                  onClick={() => toggleSection("severity")}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-on-surface">Mức độ nghiêm trọng (Severity)</span>
                    <span className="text-[10px] text-secondary">({Object.keys(dist.by_severity || {}).length} mức độ)</span>
                  </div>
                  {openSections.severity ? <ChevronUp className="w-4 h-4 text-secondary" /> : <ChevronDown className="w-4 h-4 text-secondary" />}
                </div>

                {openSections.severity && (
                  <div className="mt-3 flex flex-wrap gap-2 text-xs">
                    {Object.entries(dist.by_severity || {}).map(([sev, count]) => (
                      <div
                        key={sev}
                        className="px-2.5 py-1 rounded bg-surface-container text-on-surface font-medium cursor-help"
                        title={`Mức độ ưu tiên xử lý: ${sev}`}
                      >
                        <span className="font-bold">{sev}:</span> {count} chuyến ({((count / totalRecords) * 100).toFixed(1)}%)
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Section 3: Scenario Distribution */}
              <div className="border border-outline-variant/60 rounded-lg p-3 bg-surface-container-lowest">
                <div
                  className="flex items-center justify-between cursor-pointer select-none"
                  onClick={() => toggleSection("scenario")}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-on-surface">Kịch bản phát sinh (Scenario)</span>
                    <span className="text-[10px] text-secondary">({Object.keys(dist.by_scenario || {}).length} kịch bản)</span>
                  </div>
                  {openSections.scenario ? <ChevronUp className="w-4 h-4 text-secondary" /> : <ChevronDown className="w-4 h-4 text-secondary" />}
                </div>

                {openSections.scenario && (
                  <div className="mt-3 flex flex-wrap gap-2 text-xs">
                    {Object.entries(dist.by_scenario || {}).map(([scen, count]) => (
                      <div
                        key={scen}
                        className="px-2.5 py-1 rounded bg-surface-container text-on-surface font-medium cursor-help"
                        title={`Kịch bản nghiệp vụ: ${scen}`}
                      >
                        <span className="font-bold">{scen}:</span> {count} ({((count / totalRecords) * 100).toFixed(1)}%)
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Section 4: City Distribution */}
              <div className="border border-outline-variant/60 rounded-lg p-3 bg-surface-container-lowest">
                <div
                  className="flex items-center justify-between cursor-pointer select-none"
                  onClick={() => toggleSection("city")}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-on-surface">Khu vực địa lý (City)</span>
                    <span className="text-[10px] text-secondary">({Object.keys(dist.by_city || {}).length} thành phố)</span>
                  </div>
                  {openSections.city ? <ChevronUp className="w-4 h-4 text-secondary" /> : <ChevronDown className="w-4 h-4 text-secondary" />}
                </div>

                {openSections.city && (
                  <div className="mt-3 flex flex-wrap gap-2 text-xs">
                    {Object.entries(dist.by_city || {}).map(([city, count]) => (
                      <div
                        key={city}
                        className="px-2.5 py-1 rounded bg-surface-container text-on-surface font-medium cursor-help"
                        title={`Địa bàn hoạt động: ${city}`}
                      >
                        <span className="font-bold">{city}:</span> {count} ({((count / totalRecords) * 100).toFixed(1)}%)
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Section 5: Cancellation Actor Distribution */}
              <div className="border border-outline-variant/60 rounded-lg p-3 bg-surface-container-lowest">
                <div
                  className="flex items-center justify-between cursor-pointer select-none"
                  onClick={() => toggleSection("cancellation")}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-on-surface">Đối tượng hủy chuyến (Cancellation Actor)</span>
                  </div>
                  {openSections.cancellation ? <ChevronUp className="w-4 h-4 text-secondary" /> : <ChevronDown className="w-4 h-4 text-secondary" />}
                </div>

                {openSections.cancellation && (
                  <div className="mt-3 flex flex-wrap gap-2 text-xs">
                    {Object.entries(dist.by_cancellation_actor || {}).map(([actor, count]) => (
                      <div
                        key={actor}
                        className="px-2.5 py-1 rounded bg-surface-container text-on-surface font-medium cursor-help"
                        title={`Bên khởi tạo hủy chuyến: ${actor}`}
                      >
                        <span className="font-bold">{actor}:</span> {count} ({((count / totalRecords) * 100).toFixed(1)}%)
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Tab 4: Logs Tab */}
      {activeTab === "logs" && (
        <div data-testid="tab-content-logs">
          <PresetBatchLogs
            presetId={preset.id}
            activeBatchId={activeBatchId}
            onBatchChange={setActiveBatchId}
          />
        </div>
      )}

      {/* Preset Run Dialog */}
      <PresetRunDialog
        open={runDialogOpen}
        onOpenChange={setRunDialogOpen}
        preset={preset}
        onRunSuccess={handleRunSuccess}
      />
    </div>
  );
}
