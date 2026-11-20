"use client";

import React, { useState, useMemo } from "react";
import Link from "next/link";
import { ChevronDown, ChevronRight, ExternalLink } from "lucide-react";
import type { TestRunSummary } from "@/lib/testApiClient";

export interface HistoryTableProps {
  runs: TestRunSummary[];
}

const STATUS_LABELS: Record<string, string> = {
  IDLE: "Sẵn sàng",
  QUEUED: "Đang chuẩn bị",
  RUNNING: "Đang chạy",
  PAUSED: "Tạm dừng",
  STOP_MOVEMENT: "Đang dừng",
  CANCELLED: "Đã huỷ",
  COMPLETED: "Hoàn tất",
  FAILED: "Lỗi",
};

export function HistoryTable({ runs }: HistoryTableProps) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [sourceFilter, setSourceFilter] = useState<string>("all");
  const [labelFilter, setLabelFilter] = useState<string>("all");
  const [mismatchesOnly, setMismatchesOnly] = useState<boolean>(false);

  // Summary computations over ALL loaded runs
  const summary = useMemo(() => {
    const total = runs.length;
    let labelled = 0;
    let matches = 0;
    let mismatches = 0;
    const perClass: Record<string, number> = {};

    for (const run of runs) {
      if (run.predicted_label) {
        perClass[run.predicted_label] = (perClass[run.predicted_label] || 0) + 1;
      }
      if (run.expected_label != null && run.expected_label !== "") {
        labelled += 1;
        if (run.predicted_label === run.expected_label) {
          matches += 1;
        } else {
          mismatches += 1;
        }
      }
    }

    const accuracy = labelled > 0 ? (matches / labelled) * 100 : 0;
    return { total, labelled, matches, mismatches, accuracy, perClass };
  }, [runs]);

  // Unique sources and predicted labels for filter dropdowns
  const availableSources = useMemo(() => {
    const set = new Set<string>();
    runs.forEach((r) => {
      if (r.source) set.add(r.source);
    });
    return Array.from(set);
  }, [runs]);

  const availablePredictedLabels = useMemo(() => {
    const set = new Set<string>();
    runs.forEach((r) => {
      if (r.predicted_label) set.add(r.predicted_label);
    });
    return Array.from(set);
  }, [runs]);

  // Filtered runs
  const filteredRuns = useMemo(() => {
    return runs.filter((run) => {
      if (sourceFilter !== "all" && run.source !== sourceFilter) {
        return false;
      }
      if (labelFilter !== "all" && run.predicted_label !== labelFilter) {
        return false;
      }
      if (mismatchesOnly) {
        const isMismatch =
          run.expected_label != null &&
          run.expected_label !== "" &&
          run.predicted_label !== run.expected_label;
        if (!isMismatch) return false;
      }
      return true;
    });
  }, [runs, sourceFilter, labelFilter, mismatchesOnly]);

  const toggleRow = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const getSourceBadge = (source?: string | null) => {
    switch (source) {
      case "manual":
        return (
          <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-gs-blue-soft text-gs-blue border border-gs-blue/30">
            Thủ công
          </span>
        );
      case "preset":
        return (
          <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-gs-purple-soft text-gs-purple border border-gs-purple/30">
            Mẫu có sẵn
          </span>
        );
      case "preset_batch":
        return (
          <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-gs-amber-soft text-gs-amber border border-gs-amber/40">
            Lô mẫu
          </span>
        );
      default:
        return (
          <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-surface-container-low text-gs-mute-2 border border-gs-line-2">
            {source || "—"}
          </span>
        );
    }
  };

  const getCorrectnessPill = (predicted?: string | null, expected?: string | null) => {
    if (expected == null || expected === "") {
      return (
        <span className="px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-surface-container text-gs-mute-2 border border-gs-line-2">
          Chưa có nhãn
        </span>
      );
    }
    if (predicted === expected) {
      return (
        <span className="px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-gs-green-soft text-gs-green border border-gs-green/40">
          Khớp
        </span>
      );
    }
    return (
      <span className="px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-gs-red-soft text-gs-red border border-gs-red/40">
        Lệch
      </span>
    );
  };

  return (
    <div className="space-y-3 font-sans">
      {/* Summary Header */}
      <div
        data-testid="history-summary-header"
        className="p-3 bg-surface-container-lowest border border-outline-variant/60 rounded-lg text-xs space-y-2 shadow-xs"
      >
        <div className="flex flex-wrap items-center gap-4 text-gs-ink-2">
          <div>
            <span className="text-secondary">Tổng số: </span>
            <span data-testid="summary-total" className="font-bold text-on-surface">
              {summary.total}
            </span>
          </div>
          <div>
            <span className="text-secondary">Đã gán nhãn: </span>
            <span data-testid="summary-labelled" className="font-bold text-on-surface">
              {summary.labelled}
            </span>
          </div>
          <div>
            <span className="text-secondary">Độ chính xác: </span>
            <span data-testid="summary-accuracy" className="font-bold text-gs-green">
              {summary.accuracy.toFixed(1)}%
            </span>
          </div>
          <div>
            <span className="text-secondary">Khớp: </span>
            <span data-testid="summary-matches" className="font-bold text-gs-green">
              {summary.matches}
            </span>
          </div>
          <div>
            <span className="text-secondary">Lệch nhãn: </span>
            <span
              data-testid="summary-mismatches"
              className={`font-bold ${summary.mismatches > 0 ? "text-gs-red" : "text-gs-mute-2"}`}
            >
              {summary.mismatches}
            </span>
          </div>
        </div>

        {Object.keys(summary.perClass).length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 pt-1.5 border-t border-outline-variant/30 text-[11px]">
            <span className="text-secondary font-medium">Theo lớp dự đoán:</span>
            {Object.entries(summary.perClass).map(([cls, count]) => (
              <span
                key={cls}
                className="px-1.5 py-0.5 bg-surface-container rounded text-gs-ink-2 font-mono text-[10px]"
              >
                {cls}: <strong>{count}</strong>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Filter Toolbar */}
      <div className="flex flex-wrap items-center gap-3 p-2 bg-surface-container-lowest border border-outline-variant/50 rounded text-xs">
        <div className="flex items-center gap-1.5">
          <label htmlFor="filter-source" className="text-secondary text-[11px] font-medium">
            Lọc nguồn:
          </label>
          <select
            id="filter-source"
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
            className="px-2 py-1 text-xs border border-outline-variant rounded bg-surface focus:outline-none focus:ring-1 focus:ring-primary"
          >
            <option value="all">Tất cả nguồn</option>
            {availableSources.map((s) => (
              <option key={s} value={s}>
                {s === "manual" ? "Thủ công" : s === "preset" ? "Mẫu có sẵn" : s === "preset_batch" ? "Lô mẫu" : s}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-1.5">
          <label htmlFor="filter-label" className="text-secondary text-[11px] font-medium">
            Lọc nhãn dự đoán:
          </label>
          <select
            id="filter-label"
            value={labelFilter}
            onChange={(e) => setLabelFilter(e.target.value)}
            className="px-2 py-1 text-xs border border-outline-variant rounded bg-surface focus:outline-none focus:ring-1 focus:ring-primary"
          >
            <option value="all">Tất cả nhãn</option>
            {availablePredictedLabels.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-1.5 ml-auto">
          <label className="flex items-center gap-1 text-[11px] text-gs-ink-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={mismatchesOnly}
              onChange={(e) => setMismatchesOnly(e.target.checked)}
              className="rounded border-outline-variant text-primary focus:ring-primary"
              aria-label="Chỉ chuyến lệch nhãn"
            />
            <span>Chỉ chuyến lệch nhãn</span>
          </label>
        </div>
      </div>

      {/* Table */}
      {filteredRuns.length === 0 ? (
        <p className="text-xs text-secondary italic py-4 text-center">
          Không tìm thấy chuyến đi nào phù hợp với bộ lọc.
        </p>
      ) : (
        <div className="overflow-x-auto border border-outline-variant/60 rounded-lg">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="bg-surface-container-low text-left text-secondary border-b border-outline-variant/60">
                <th className="w-6 py-2 px-2"></th>
                <th className="py-2 px-2.5 whitespace-nowrap">Chuyến đi</th>
                <th className="py-2 px-2 whitespace-nowrap">Nguồn</th>
                <th className="py-2 px-2 whitespace-nowrap">Tài xế / Biển số</th>
                <th className="py-2 px-2 whitespace-nowrap">Vụ việc (Case ID)</th>
                <th className="py-2 px-2.5 min-w-[200px]">Lộ trình (Điểm đi → Đón → Đến)</th>
                <th className="py-2 px-2 whitespace-nowrap">Trạng thái</th>
                <th className="py-2 px-2 whitespace-nowrap">Dự đoán</th>
                <th className="py-2 px-2 whitespace-nowrap">Kỳ vọng</th>
                <th className="py-2 px-2 whitespace-nowrap">Độ chính xác</th>
                <th className="py-2 px-2 whitespace-nowrap">Loại lỗi</th>
                <th className="py-2 px-2 whitespace-nowrap">Độ tin cậy</th>
              </tr>
            </thead>
            <tbody>
              {filteredRuns.map((run) => {
                const isExpanded = expandedIds.has(run.id);
                const titleOrTrip = run.title || run.trip_id || "Chuyến chưa đặt tên";
                const isErrorPrediction = Boolean(run.predicted_label?.startsWith("ERR-"));
                const hasCaseId = Boolean(run.case_id);
                const fullRoute = `${run.origin_address || "—"} → ${run.pickup_address || "—"} → ${run.destination_address || "—"}`;

                return (
                  <React.Fragment key={run.id}>
                    <tr className="border-b border-outline-variant/30 hover:bg-surface-container-low/50 transition-colors">
                      <td className="py-2 px-1 text-center">
                        <button
                          type="button"
                          onClick={() => toggleRow(run.id)}
                          aria-label={`Chi tiết chuyến ${titleOrTrip}`}
                          className="p-1 rounded hover:bg-surface-container text-gs-mute-2"
                        >
                          {isExpanded ? (
                            <ChevronDown className="w-3.5 h-3.5" />
                          ) : (
                            <ChevronRight className="w-3.5 h-3.5" />
                          )}
                        </button>
                      </td>

                      <td className="py-2 px-2.5 font-semibold text-on-surface whitespace-nowrap">
                        {titleOrTrip}
                      </td>

                      <td className="py-2 px-2 whitespace-nowrap">
                        {getSourceBadge(run.source)}
                      </td>

                      <td className="py-2 px-2 whitespace-nowrap text-gs-ink-2">
                        <div>{run.driver_name || "—"}</div>
                        <div className="text-[11px] font-mono text-gs-mute-2">{run.license_plate || "—"}</div>
                      </td>

                      <td className="py-2 px-2 whitespace-nowrap font-mono text-[11px]">
                        {isErrorPrediction && hasCaseId ? (
                          <Link
                            href={`/workplace?caseId=${encodeURIComponent(run.case_id!)}`}
                            className="inline-flex items-center gap-1 text-primary hover:underline font-semibold"
                          >
                            <span>{run.case_id}</span>
                            <ExternalLink className="w-3 h-3" />
                          </Link>
                        ) : (
                          <span className="text-gs-mute-2">{run.case_id || "—"}</span>
                        )}
                      </td>

                      <td className="py-2 px-2.5 max-w-[240px]">
                        <div
                          data-testid="route-flow"
                          title={fullRoute}
                          className="truncate text-[11px] text-gs-mute-2 cursor-help"
                        >
                          <span>{run.origin_address || "—"}</span>
                          <span className="text-gs-mute mx-1">→</span>
                          <span>{run.pickup_address || "—"}</span>
                          <span className="text-gs-mute mx-1">→</span>
                          <span>{run.destination_address || "—"}</span>
                        </div>
                      </td>

                      <td className="py-2 px-2 whitespace-nowrap text-gs-ink-2">
                        {STATUS_LABELS[run.status] || run.status}
                      </td>

                      <td className="py-2 px-2 whitespace-nowrap font-mono font-bold text-[11px]">
                        {run.predicted_label || "—"}
                      </td>

                      <td className="py-2 px-2 whitespace-nowrap font-mono text-[11px] text-gs-mute-2">
                        {run.expected_label || "—"}
                      </td>

                      <td className="py-2 px-2 whitespace-nowrap">
                        {getCorrectnessPill(run.predicted_label, run.expected_label)}
                      </td>

                      <td className="py-2 px-2 whitespace-nowrap font-mono text-[11px] text-gs-mute-2">
                        {run.error_type || "—"}
                      </td>

                      <td className="py-2 px-2 whitespace-nowrap text-right font-mono font-medium text-[11px]">
                        {run.confidence != null
                          ? `${(run.confidence * 100).toFixed(1)}%`
                          : "—"}
                      </td>
                    </tr>

                    {/* Expandable details row */}
                    {isExpanded && (
                      <tr className="bg-surface-container-low/30 border-b border-outline-variant/30">
                        <td colSpan={12} className="p-3 text-[11px] text-gs-ink-2">
                          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                            <div className="space-y-1">
                              <div className="font-semibold text-secondary">Thời gian</div>
                              <div>
                                Tạo lúc:{" "}
                                <span className="font-mono text-gs-mute-2">
                                  {new Date(run.created_at).toLocaleString()}
                                </span>
                              </div>
                              <div>
                                Hoàn tất lúc:{" "}
                                <span className="font-mono text-gs-mute-2">
                                  {run.completed_at
                                    ? new Date(run.completed_at).toLocaleString()
                                    : "—"}
                                </span>
                              </div>
                            </div>

                            <div className="space-y-1">
                              <div className="font-semibold text-secondary">Thông tin huỷ chuyến</div>
                              <div>
                                Người huỷ:{" "}
                                <span data-testid="cancel-actor-detail" className="text-gs-mute-2">
                                  {run.cancellation_actor === "driver"
                                    ? "Tài xế"
                                    : run.cancellation_actor === "customer"
                                    ? "Khách hàng"
                                    : run.cancellation_actor || "—"}
                                </span>
                              </div>
                              <div>
                                Lý do huỷ:{" "}
                                <span className="text-gs-mute-2">
                                  {run.cancellation_reason || "—"}
                                </span>
                              </div>
                            </div>

                            <div className="space-y-1">
                              <div className="font-semibold text-secondary">Lộ trình đầy đủ</div>
                              <div>
                                <span className="text-gs-mute-2">Điểm xuất phát: </span>
                                {run.origin_address || "—"}
                              </div>
                              <div>
                                <span className="text-gs-mute-2">Điểm đón khách: </span>
                                {run.pickup_address || "—"}
                              </div>
                              <div>
                                <span className="text-gs-mute-2">Điểm đến: </span>
                                {run.destination_address || "—"}
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
