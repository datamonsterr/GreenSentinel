"use client";

import React, { useEffect, useState, useRef, useTransition } from "react";
import {
  cancelPresetBatchRun,
  fetchPresetBatchRunDetail,
  type PresetBatchEvent,
  type PresetBatchRunDetailResponse,
  type PresetBatchTrip,
} from "@/lib/testApiClient";
import { observePresetBatchRun } from "@/lib/preset-batch-stream";
import {
  AlertCircle,
  Ban,
  ChevronDown,
  ChevronRight,
  Clock,
  Compass,
  Gauge,
  Loader2,
  MessageSquare,
  RefreshCw,
  ShieldCheck,
  User,
} from "lucide-react";

export interface PresetBatchLogsProps {
  presetId: string;
  activeBatchId?: string | null;
  onBatchChange?: (batchId: string | null) => void;
}

export function PresetBatchLogs({
  presetId,
  activeBatchId,
  onBatchChange,
}: PresetBatchLogsProps) {
  const [currentBatchId, setCurrentBatchId] = useState<string | null>(() => {
    if (activeBatchId) return activeBatchId;
    if (typeof window !== "undefined") {
      try {
        return localStorage.getItem(`preset_latest_batch_${presetId}`);
      } catch {
        return null;
      }
    }
    return null;
  });
  const [batchDetail, setBatchDetail] = useState<PresetBatchRunDetailResponse | null>(null);
  const [events, setEvents] = useState<PresetBatchEvent[]>([]);
  const [expandedTrips, setExpandedTrips] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [streamState, setStreamState] = useState<"connected" | "reconnecting" | "closed">("closed");

  // Sync if activeBatchId changes from props
  useEffect(() => {
    if (activeBatchId && activeBatchId !== currentBatchId) {
      setCurrentBatchId(activeBatchId);
    }
  }, [activeBatchId, currentBatchId]);

  // Fetch batch detail when currentBatchId changes
  const loadBatch = async (batchId: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchPresetBatchRunDetail(batchId);
      setBatchDetail(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể tải nhật ký đợt chạy");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!currentBatchId) {
      setBatchDetail(null);
      setEvents([]);
      return;
    }
    void loadBatch(currentBatchId);
  }, [currentBatchId]);

  // SSE subscription
  useEffect(() => {
    if (!currentBatchId || !batchDetail) return;
    if (["COMPLETED", "CANCELLED", "FAILED"].includes(batchDetail.status)) {
      setStreamState("closed");
      return;
    }

    const abortController = new AbortController();

    void observePresetBatchRun(currentBatchId, abortController.signal, {
      onConnection: (state) => setStreamState(state),
      onReconcile: (reconciled) => {
        setBatchDetail(reconciled);
      },
      onEvent: (evt) => {
        setEvents((prev) => [...prev, evt]);

        if (evt.event_type === "batch.completed") {
          setBatchDetail((prev) => prev ? { ...prev, status: "COMPLETED" } : null);
          setStreamState("closed");
        } else if (evt.event_type === "batch.cancelled") {
          setBatchDetail((prev) => prev ? { ...prev, status: "CANCELLED" } : null);
          setStreamState("closed");
        }

        // Incrementally update trip state from event
        if (evt.trip_ref) {
          setBatchDetail((prev) => {
            if (!prev) return null;
            const updatedTrips = prev.trips.map((t) => {
              if (t.trip_ref !== evt.trip_ref) return t;

              const next = { ...t };
              if (evt.event_type === "trip.started") {
                next.status = "RUNNING";
              } else if (evt.event_type === "trip.classified") {
                next.status = "COMPLETED";
                next.predicted_label = evt.label ?? next.predicted_label;
                next.confidence = evt.confidence ?? next.confidence;
              } else if (evt.event_type === "trip.case_created") {
                next.case_id = evt.case_id ?? next.case_id;
              } else if (evt.event_type === "trip.failed") {
                next.status = "FAILED";
                next.error = evt.reason ?? next.error;
              } else if (evt.event_type === "trip.skipped") {
                next.status = "SKIPPED";
              }

              if (evt.driver_id) next.driver_id = evt.driver_id;
              if (evt.driver_name) next.driver_name = evt.driver_name;
              return next;
            });
            return { ...prev, trips: updatedTrips };
          });
        }
      },
    });

    return () => {
      abortController.abort();
    };
  }, [currentBatchId, batchDetail?.status]);

  const handleCancelBatch = async () => {
    if (!currentBatchId) return;
    setCancelling(true);
    try {
      const updated = await cancelPresetBatchRun(currentBatchId);
      setBatchDetail((prev) => (prev ? { ...prev, status: updated.status } : null));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể hủy đợt chạy");
    } finally {
      setCancelling(false);
    }
  };

  const toggleExpand = (tripRef: string) => {
    setExpandedTrips((prev) => ({ ...prev, [tripRef]: !prev[tripRef] }));
  };

  if (!currentBatchId) {
    return (
      <div className="text-center py-12 text-xs text-secondary border border-dashed rounded-lg">
        Chưa có đợt chạy nào cho chuyến mẫu này. Nhấp vào nút &quot;Chạy&quot; ở trên để bắt đầu đợt mô phỏng.
      </div>
    );
  }

  const isTerminal = ["COMPLETED", "CANCELLED", "FAILED"].includes(batchDetail?.status || "");

  // Group events by trip_ref for quick lookup
  const eventsByTrip = events.reduce<Record<string, PresetBatchEvent[]>>((acc, evt) => {
    if (evt.trip_ref) {
      if (!acc[evt.trip_ref]) acc[evt.trip_ref] = [];
      acc[evt.trip_ref].push(evt);
    }
    return acc;
  }, {});

  return (
    <div className="space-y-4">
      {/* Header controls & summary */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-lg border border-outline-variant/60 bg-surface-container-lowest">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold font-mono">Đợt #{currentBatchId.slice(0, 8)}</span>
            <span
              className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase ${
                batchDetail?.status === "RUNNING"
                  ? "bg-primary-fixed text-on-primary-fixed animate-pulse"
                  : batchDetail?.status === "COMPLETED"
                  ? "bg-gs-blue-soft text-gs-blue"
                  : batchDetail?.status === "CANCELLED"
                  ? "bg-surface-container-high text-gs-ink-2"
                  : "bg-gs-amber-soft text-gs-amber"
              }`}
            >
              {batchDetail?.status || "ĐANG TẢI…"}
            </span>
            {streamState === "connected" && (
              <span className="flex items-center gap-1 text-[10px] text-primary font-medium">
                <span className="w-1.5 h-1.5 rounded-full bg-gs-green animate-ping" />
                SSE Trực tiếp
              </span>
            )}
            {streamState === "reconnecting" && (
              <span className="text-[10px] text-gs-amber font-medium flex items-center gap-1">
                <Loader2 className="w-3 h-3 animate-spin" /> Đang kết nối lại…
              </span>
            )}
          </div>
          <div className="text-[11px] text-secondary flex items-center gap-2">
            <span>Khởi tạo lúc: {batchDetail?.created_at ? new Date(batchDetail.created_at).toLocaleTimeString("vi-VN") : "—"}</span>
            {batchDetail?.counters && (
              <span>
                · Hoàn tất: {batchDetail.counters.completed ?? 0} / {batchDetail.trips.length}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void loadBatch(currentBatchId)}
            disabled={loading}
            className="flex items-center gap-1 text-xs px-2.5 py-1 rounded border border-outline-variant/60 hover:bg-surface-container transition"
            title="Tải lại trạng thái"
          >
            <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} />
            <span>Tải lại</span>
          </button>

          {!isTerminal && (
            <button
              type="button"
              onClick={handleCancelBatch}
              disabled={cancelling}
              className="flex items-center gap-1 text-xs px-2.5 py-1 rounded bg-gs-red text-white font-medium hover:bg-gs-red/90 disabled:opacity-50 transition"
            >
              {cancelling ? <Loader2 className="w-3 h-3 animate-spin" /> : <Ban className="w-3 h-3" />}
              <span>Hủy đợt chạy</span>
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 p-2.5 text-xs rounded bg-error-container text-error border border-error/30">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Trips list grouped in processing order */}
      <div className="space-y-2">
        <h4 className="text-xs font-bold text-on-surface">
          Danh sách chuyến trong đợt ({batchDetail?.trips?.length || 0})
        </h4>

        {loading && !batchDetail ? (
          <div className="flex items-center justify-center py-8 text-xs text-secondary gap-2">
            <Loader2 className="w-4 h-4 animate-spin" /> Đang tải thông tin chuyến…
          </div>
        ) : (
          batchDetail?.trips?.map((trip: PresetBatchTrip) => {
            const isExpanded = Boolean(expandedTrips[trip.trip_ref]);
            const tripEvents = eventsByTrip[trip.trip_ref] || [];
            const snapshot = (trip.snapshot || {}) as {
              conversation?: Array<{ role: string; text: string; sent_at_offset_s?: number }>;
              gps_summary?: {
                points?: number;
                bbox?: { min_lat: number; max_lat: number; min_lon: number; max_lon: number };
                mock_location_count?: number;
                max_accuracy_m?: number;
              };
              speed_stats?: { min_mps?: number; avg_mps?: number; max_mps?: number };
              driver_name?: string;
              driver_id?: string;
            };

            const reachedClassifier =
              Boolean(trip.predicted_label) ||
              tripEvents.some((e) => e.reached_classifier || e.event_type === "trip.classifier_received" || e.event_type === "trip.classified");

            return (
              <div
                key={trip.id}
                className="border border-outline-variant/60 rounded-lg bg-surface-container-lowest overflow-hidden transition"
                data-testid={`trip-group-${trip.trip_ref}`}
              >
                {/* Trip Group Header Row */}
                <div
                  onClick={() => toggleExpand(trip.trip_ref)}
                  className="flex flex-wrap items-center justify-between gap-2 p-2.5 cursor-pointer hover:bg-surface-container-low transition select-none"
                  data-testid={`trip-header-${trip.trip_ref}`}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-secondary text-[10px] w-5 font-mono">#{trip.order + 1}</span>
                    {isExpanded ? (
                      <ChevronDown className="w-3.5 h-3.5 text-secondary" />
                    ) : (
                      <ChevronRight className="w-3.5 h-3.5 text-secondary" />
                    )}
                    <span className="font-mono font-bold text-xs text-primary truncate">{trip.trip_ref}</span>
                    {trip.expected_label && (
                      <span className="text-[11px] px-1.5 py-0.5 rounded bg-surface-container font-medium text-secondary">
                        Kỳ vọng: {trip.expected_label}
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-2">
                    {/* Status Pill */}
                    <span
                      className={`text-[10px] font-bold px-2 py-0.5 rounded-full uppercase ${
                        trip.status === "COMPLETED"
                          ? "bg-primary-fixed text-on-primary-fixed"
                          : trip.status === "RUNNING"
                          ? "bg-gs-blue-soft text-gs-blue animate-pulse"
                          : trip.status === "FAILED"
                          ? "bg-gs-red-soft text-gs-red"
                          : trip.status === "SKIPPED"
                          ? "bg-surface-container text-gs-ink-2"
                          : "bg-gs-amber-soft text-gs-amber"
                      }`}
                    >
                      {trip.status}
                    </span>

                    {/* Classifier Badge */}
                    <span
                      className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
                        reachedClassifier ? "bg-primary-fixed text-on-primary-fixed border border-primary-fixed-dim" : "bg-surface-container-low text-gs-mute-2"
                      }`}
                      title="Chuyến đã qua mô hình phân loại vi phạm"
                    >
                      {reachedClassifier ? "Classifier: Có" : "Classifier: Chưa"}
                    </span>

                    {/* Predicted Label & Confidence */}
                    {trip.predicted_label && (
                      <span className="text-[11px] font-bold text-on-surface bg-surface-container px-2 py-0.5 rounded">
                        Dự đoán: {trip.predicted_label}
                        {trip.confidence != null && (
                          <span className="text-secondary font-normal ml-1">
                            ({(trip.confidence * 100).toFixed(1)}%)
                          </span>
                        )}
                      </span>
                    )}

                    {/* Assigned Driver */}
                    <span className="flex items-center gap-1 text-[11px] text-secondary">
                      <User className="w-3 h-3 text-secondary" />
                      <span>{trip.driver_name || snapshot.driver_name || "Tài xế"}</span>
                    </span>
                  </div>
                </div>

                {/* Expanded Details */}
                {isExpanded && (
                  <div
                    className="p-3 border-t border-outline-variant/40 bg-surface-container-lowest space-y-3"
                    data-testid={`trip-details-${trip.trip_ref}`}
                  >
                    {/* 1. Event Timeline */}
                    <div>
                      <div className="text-[11px] font-bold text-on-surface uppercase mb-1.5 flex items-center gap-1">
                        <Clock className="w-3 h-3 text-secondary" />
                        <span>Dòng sự kiện (Event Timeline)</span>
                      </div>
                      {tripEvents.length === 0 ? (
                        <div className="text-[11px] text-secondary italic">Chưa ghi nhận sự kiện SSE nào.</div>
                      ) : (
                        <div className="space-y-1 border-l-2 border-primary/30 pl-2.5 ml-1">
                          {tripEvents.map((evt, idx) => (
                            <div key={evt.event_id || idx} className="text-[11px] flex items-start justify-between gap-2">
                              <div>
                                <span className="font-mono font-semibold text-primary">{evt.event_type}</span>
                                {evt.reason && <span className="text-gs-red ml-1">({evt.reason})</span>}
                                {evt.label && (
                                  <span className="ml-1 text-on-surface">
                                    · nhãn: {evt.label} ({(Number(evt.confidence || 0) * 100).toFixed(1)}%)
                                  </span>
                                )}
                                {evt.case_id && (
                                  <span className="ml-1 text-on-primary-fixed font-mono">
                                    · case #{evt.case_id.slice(0, 8)}
                                  </span>
                                )}
                              </div>
                              <span className="text-[10px] text-secondary shrink-0">
                                {new Date(evt.occurred_at).toLocaleTimeString("vi-VN")}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* 2. Conversation History */}
                    <div>
                      <div className="text-[11px] font-bold text-on-surface uppercase mb-1 flex items-center gap-1">
                        <MessageSquare className="w-3 h-3 text-secondary" />
                        <span>Lịch sử hội thoại ({snapshot.conversation?.length || 0})</span>
                      </div>
                      {!snapshot.conversation || snapshot.conversation.length === 0 ? (
                        <div className="text-[11px] text-secondary italic">Không có tin nhắn nào.</div>
                      ) : (
                        <div className="space-y-1 max-h-32 overflow-y-auto border border-outline-variant/40 rounded p-2 bg-surface-container">
                          {snapshot.conversation.map((msg, i) => (
                            <div key={i} className="text-[11px] flex gap-2">
                              <span className="font-bold text-[10px] uppercase text-secondary shrink-0">
                                {msg.role === "driver" ? "Tài xế:" : "Khách:"}
                              </span>
                              <span className="text-on-surface">{msg.text}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* 3. GPS Summary & Speed Stats */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2 pt-1">
                      {/* GPS Summary */}
                      <div className="border border-outline-variant/40 rounded p-2 bg-surface-container">
                        <div className="text-[10px] font-bold uppercase text-secondary mb-1 flex items-center gap-1">
                          <Compass className="w-3 h-3" />
                          <span>Tóm tắt GPS</span>
                        </div>
                        <div className="text-[11px] space-y-0.5">
                          <div>Điểm tọa độ: <span className="font-semibold">{snapshot.gps_summary?.points ?? 0}</span></div>
                          <div>Mock GPS: <span className="font-semibold">{snapshot.gps_summary?.mock_location_count ?? 0}</span></div>
                          {snapshot.gps_summary?.max_accuracy_m != null && (
                            <div>Độ chính xác tối đa: <span className="font-semibold">{snapshot.gps_summary.max_accuracy_m} m</span></div>
                          )}
                          {snapshot.gps_summary?.bbox && (
                            <div className="text-[10px] text-secondary font-mono truncate">
                              BBox: [{snapshot.gps_summary.bbox.min_lat.toFixed(3)}, {snapshot.gps_summary.bbox.min_lon.toFixed(3)}]
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Speed Stats */}
                      <div className="border border-outline-variant/40 rounded p-2 bg-surface-container">
                        <div className="text-[10px] font-bold uppercase text-secondary mb-1 flex items-center gap-1">
                          <Gauge className="w-3 h-3" />
                          <span>Thống kê vận tốc</span>
                        </div>
                        <div className="text-[11px] space-y-0.5">
                          <div>Vận tốc nhỏ nhất: <span className="font-semibold">{snapshot.speed_stats?.min_mps ?? 0} m/s</span></div>
                          <div>Vận tốc trung bình: <span className="font-semibold">{snapshot.speed_stats?.avg_mps ?? 0} m/s</span></div>
                          <div>Vận tốc tối đa: <span className="font-semibold">{snapshot.speed_stats?.max_mps ?? 0} m/s</span></div>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
