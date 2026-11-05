"use client";

import React, { useState } from "react";
import {
  CheckCircle2,
  Clock,
  Circle,
  XCircle,
  ChevronRight,
  Info,
  X,
} from "lucide-react";
import type { TestRunTraceStage } from "@/lib/testApiClient";

export interface TripPipelineProps {
  stages?: TestRunTraceStage[];
  status?: string;
  className?: string;
}

export interface PipelineStageConfig {
  key: string;
  name: string;
  defaultDesc: string;
}

export const CANONICAL_STAGES: PipelineStageConfig[] = [
  { key: "created", name: "Khởi tạo", defaultDesc: "Khởi tạo chuyến đi" },
  { key: "driving_to_pickup", name: "Tới điểm đón", defaultDesc: "Tài xế di chuyển tới điểm đón" },
  { key: "picked_up", name: "Đã đón khách", defaultDesc: "Khách đã lên xe" },
  { key: "driving_to_destination", name: "Tới điểm trả", defaultDesc: "Xe đang chạy tới điểm đến" },
  { key: "completed", name: "Hoàn tất / Đã hủy", defaultDesc: "Kết thúc hành trình" },
  { key: "published", name: "Xuất bản", defaultDesc: "Xuất bản sự kiện chuyến đi" },
  { key: "classifier_received", name: "Nhận tín hiệu", defaultDesc: "Bộ phân loại nhận telemetry" },
  { key: "classified", name: "Đã phân loại", defaultDesc: "Kết quả đánh giá vi phạm" },
  { key: "case_created", name: "Hồ sơ", defaultDesc: "Hồ sơ phân tích gian lận" },
];

function formatTime(isoStr: string | null | undefined): string {
  if (!isoStr) return "—";
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;
    return d.toLocaleTimeString("vi-VN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return isoStr;
  }
}

function getStageDescription(stage: TestRunTraceStage, config?: PipelineStageConfig): string {
  const detail = stage.detail;
  if (detail && typeof detail === "object") {
    if ("reason" in detail && typeof detail.reason === "string") {
      const actor = "actor" in detail ? String(detail.actor) : "hệ thống";
      return `Hủy bởi ${actor}: ${detail.reason}`;
    }
    if ("label" in detail && typeof detail.label === "string") {
      const conf = "confidence" in detail && typeof detail.confidence === "number"
        ? ` (${(detail.confidence * 100).toFixed(0)}%)`
        : "";
      return `Nhãn: ${detail.label}${conf}`;
    }
    if ("case_id" in detail && typeof detail.case_id === "string") {
      return `Mã hồ sơ: ${detail.case_id}`;
    }
    if ("destination" in detail && typeof detail.destination === "string") {
      return `Đích: ${detail.destination}`;
    }
    if ("title" in detail && typeof detail.title === "string") {
      return detail.title;
    }
  } else if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  return config?.defaultDesc || "Chờ xử lý";
}

export function TripPipeline({
  stages = [],
  status = "IDLE",
  className = "",
}: TripPipelineProps) {
  const [selectedStage, setSelectedStage] = useState<{
    stage: TestRunTraceStage;
    config: PipelineStageConfig;
    index: number;
  } | null>(null);

  // Merge canonical 9 stages with incoming stages
  const resolvedStages = CANONICAL_STAGES.map((cfg, idx) => {
    // Find matching stage from backend response
    const matched = stages.find((s) => {
      if (cfg.key === "completed") {
        return s.stage === "completed" || s.stage === "cancelled";
      }
      return s.stage === cfg.key;
    });

    if (matched) {
      return {
        stage: matched,
        config: cfg,
        index: idx,
      };
    }

    // Default waiting stage
    const fallback: TestRunTraceStage = {
      stage: cfg.key,
      state: "waiting",
      occurred_at: null,
      detail: null,
    };
    return {
      stage: fallback,
      config: cfg,
      index: idx,
    };
  });

  // Determine current active step:
  // 1. Stage with state === "active"
  // 2. If running, first stage with state === "waiting"
  // 3. Otherwise, last stage with state === "done"
  let currentStepIndex = -1;
  const activeIdx = resolvedStages.findIndex((item) => item.stage.state === "active");
  if (activeIdx !== -1) {
    currentStepIndex = activeIdx;
  } else if (status === "RUNNING") {
    const firstWaitingIdx = resolvedStages.findIndex((item) => item.stage.state === "waiting");
    currentStepIndex = firstWaitingIdx !== -1 ? firstWaitingIdx : resolvedStages.length - 1;
  } else {
    for (let i = resolvedStages.length - 1; i >= 0; i--) {
      if (resolvedStages[i].stage.state === "done") {
        currentStepIndex = i;
        break;
      }
    }
    if (currentStepIndex === -1 && resolvedStages.length > 0) {
      currentStepIndex = 0;
    }
  }

  return (
    <div data-testid="trip-pipeline" className={`w-full flex flex-col gap-2 ${className}`}>
      {/* Horizontal stages container */}
      <div
        className="flex items-stretch gap-2 overflow-x-auto pb-2 pt-1 px-1 scrollbar-thin"
        role="list"
        aria-label="Tiến trình chuyến đi"
      >
        {resolvedStages.map((item, idx) => {
          const isCurrent = idx === currentStepIndex;
          const { stage, config } = item;
          const isDone = stage.state === "done";
          const isCancelled = stage.stage === "cancelled";
          const desc = getStageDescription(stage, config);

          return (
            <div key={config.key} className="flex items-center shrink-0">
              <button
                type="button"
                onClick={() => setSelectedStage(item)}
                aria-label={`Chi tiết giai đoạn ${idx + 1}: ${config.name}`}
                data-testid={`pipeline-stage-${idx + 1}`}
                data-stage-key={config.key}
                data-state={stage.state}
                data-current={isCurrent ? "true" : "false"}
                className={`w-40 sm:w-44 text-left p-2.5 rounded-lg border transition-all cursor-pointer flex flex-col justify-between gap-1.5 shadow-2xs ${
                  isCurrent
                    ? "border-primary bg-primary/5 ring-2 ring-primary/30 shadow-xs"
                    : isDone
                    ? isCancelled
                      ? "border-rose-300 bg-rose-50/50 hover:bg-rose-50"
                      : "border-emerald-300 bg-emerald-50/40 hover:bg-emerald-50"
                    : "border-outline-variant/60 bg-white hover:bg-slate-50"
                }`}
              >
                {/* Header: step number & state icon */}
                <div className="flex items-center justify-between gap-1 w-full">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span
                      className={`w-4 h-4 rounded-full text-[10px] font-bold flex items-center justify-center shrink-0 ${
                        isCurrent
                          ? "bg-primary text-white"
                          : isDone
                          ? isCancelled
                            ? "bg-rose-600 text-white"
                            : "bg-emerald-600 text-white"
                          : "bg-slate-200 text-slate-600"
                      }`}
                    >
                      {idx + 1}
                    </span>
                    <span className="font-bold text-xs truncate text-slate-800">
                      {isCancelled ? "Đã hủy" : config.name}
                    </span>
                  </div>

                  <div className="shrink-0">
                    {isCancelled ? (
                      <XCircle className="w-4 h-4 text-rose-600" />
                    ) : isDone ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                    ) : isCurrent ? (
                      <Clock className="w-4 h-4 text-primary animate-spin" />
                    ) : (
                      <Circle className="w-4 h-4 text-slate-300" />
                    )}
                  </div>
                </div>

                {/* Body: description */}
                <p className="text-[11px] text-slate-600 line-clamp-2 min-h-[30px]" title={desc}>
                  {desc}
                </p>

                {/* Footer: timestamp */}
                <div className="flex items-center justify-between text-[10px] font-mono text-slate-500 pt-1 border-t border-slate-100 w-full">
                  <span>{formatTime(stage.occurred_at)}</span>
                  <span
                    className={`px-1.5 py-0.2 rounded text-[9px] font-semibold uppercase ${
                      isCancelled
                        ? "bg-rose-100 text-rose-800"
                        : isDone
                        ? "bg-emerald-100 text-emerald-800"
                        : isCurrent
                        ? "bg-primary/20 text-primary"
                        : "bg-slate-100 text-slate-500"
                    }`}
                  >
                    {isCancelled ? "cancelled" : stage.state}
                  </span>
                </div>
              </button>

              {idx < resolvedStages.length - 1 && (
                <div className="px-1 text-slate-300 shrink-0">
                  <ChevronRight className="w-4 h-4" />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Stage Detail Modal / Popover */}
      {selectedStage && (
        <div
          role="dialog"
          aria-label={`Chi tiết giai đoạn ${selectedStage.config.name}`}
          className="p-3 bg-white border border-primary/40 rounded-lg shadow-sm space-y-2 animate-fade-in text-xs"
        >
          <div className="flex items-center justify-between border-b border-outline-variant/30 pb-1.5">
            <div className="flex items-center gap-2">
              <Info className="w-4 h-4 text-primary" />
              <span className="font-bold text-slate-800 text-sm">
                Giai đoạn {selectedStage.index + 1}: {selectedStage.config.name}
              </span>
              <span
                className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${
                  selectedStage.stage.state === "done"
                    ? "bg-emerald-100 text-emerald-800"
                    : "bg-slate-100 text-slate-600"
                }`}
              >
                {selectedStage.stage.state}
              </span>
            </div>
            <button
              type="button"
              onClick={() => setSelectedStage(null)}
              aria-label="Đóng chi tiết"
              className="p-1 text-slate-400 hover:text-slate-600 rounded cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="grid grid-cols-2 gap-2 text-[11px]">
            <div>
              <span className="text-slate-500 block">Thời gian ghi nhận:</span>
              <span className="font-mono font-semibold text-slate-700">
                {selectedStage.stage.occurred_at || "Chưa có"}
              </span>
            </div>
            <div>
              <span className="text-slate-500 block">Mô tả hệ thống:</span>
              <span className="text-slate-700">
                {getStageDescription(selectedStage.stage, selectedStage.config)}
              </span>
            </div>
          </div>

          {selectedStage.stage.detail && (
            <div className="space-y-1">
              <span className="text-slate-500 text-[10px] uppercase font-bold tracking-wider">
                Chi tiết dữ liệu (Backend detail):
              </span>
              <pre
                data-testid="stage-detail-json"
                className="p-2 bg-slate-50 border border-slate-200 rounded font-mono text-[10px] overflow-x-auto max-h-40"
              >
                {typeof selectedStage.stage.detail === "object"
                  ? JSON.stringify(selectedStage.stage.detail, null, 2)
                  : String(selectedStage.stage.detail)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
