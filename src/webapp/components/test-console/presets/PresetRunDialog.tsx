"use client";

import React, { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  createPresetBatchRun,
  fetchClerkLinkedDrivers,
  type ClerkLinkedDriver,
  type PresetBatchRunCreate,
  type PresetBatchRunResponse,
  type TestPreset,
  type TestPresetDetailResponse,
} from "@/lib/testApiClient";
import { DriverChecklist } from "./DriverChecklist";
import { AlertCircle, Loader2, Play } from "lucide-react";

export interface PresetRunDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  preset: TestPreset | TestPresetDetailResponse;
  onRunSuccess?: (batchRun: PresetBatchRunResponse) => void;
}

export function PresetRunDialog({
  open,
  onOpenChange,
  preset,
  onRunSuccess,
}: PresetRunDialogProps) {
  const totalAvailable =
    preset.available_trips ||
    (preset as TestPresetDetailResponse).trip_count ||
    preset.selection_size ||
    10;

  const [drivers, setDrivers] = useState<ClerkLinkedDriver[]>([]);
  const [selectedDriverIds, setSelectedDriverIds] = useState<string[]>([]);
  const [driversLoading, setDriversLoading] = useState(false);

  const [isFullRun, setIsFullRun] = useState(false);
  const [tripCount, setTripCount] = useState<number>(() => Math.min(10, totalAvailable));
  const [tripsPerBatch, setTripsPerBatch] = useState<number>(1);
  const [intervalS, setIntervalS] = useState<number>(2.0);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch drivers when dialog is opened
  useEffect(() => {
    if (!open) {
      setError(null);
      return;
    }

    let active = true;
    setDriversLoading(true);
    fetchClerkLinkedDrivers()
      .then((data) => {
        if (!active) return;
        setDrivers(data);
        // Default to select all active drivers
        setSelectedDriverIds(data.map((d) => d.driver_id));
      })
      .catch((err) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Không tải được danh sách tài xế");
      })
      .finally(() => {
        if (active) setDriversLoading(false);
      });

    return () => {
      active = false;
    };
  }, [open]);

  // Handle 100% toggle
  const handleToggle100 = (checked: boolean) => {
    setIsFullRun(checked);
    if (checked) {
      setTripCount(totalAvailable);
    }
  };

  const handleSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = Number.parseInt(e.target.value, 10);
    setTripCount(val);
    if (val === totalAvailable) {
      setIsFullRun(true);
    } else {
      setIsFullRun(false);
    }
  };

  const isRunDisabled =
    selectedDriverIds.length === 0 ||
    isSubmitting ||
    tripsPerBatch < 1 ||
    intervalS <= 0 ||
    !preset.available;

  const handleStartRun = async () => {
    if (isRunDisabled) return;
    setError(null);
    setIsSubmitting(true);

    const payload: PresetBatchRunCreate = {
      trip_limit: isFullRun ? null : tripCount,
      trips_per_batch: tripsPerBatch,
      interval_s: intervalS,
      driver_ids: selectedDriverIds,
    };

    try {
      const res = await createPresetBatchRun(preset.id, payload);
      try {
        localStorage.setItem(`preset_latest_batch_${preset.id}`, res.id);
      } catch {
        // Ignore localStorage errors
      }
      onOpenChange(false);
      onRunSuccess?.(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Không thể khởi chạy đợt mô phỏng");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md p-6 space-y-4">
        <DialogHeader className="p-0 border-none">
          <DialogTitle className="text-base font-bold flex items-center gap-2">
            <Play className="w-4 h-4 text-primary fill-primary" />
            <span>Khởi chạy đợt mô phỏng</span>
          </DialogTitle>
          <DialogDescription className="text-xs text-secondary">
            Cấu hình số lượng chuyến, tần suất phát và phân bổ tài xế cho tập chuyến:{" "}
            <span className="font-semibold text-on-surface">{preset.title}</span>.
          </DialogDescription>
        </DialogHeader>

        {error && (
          <div
            className="flex items-start gap-2 p-3 text-xs rounded bg-error-container text-error border border-error/30"
            role="alert"
          >
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            <div className="flex-1">{error}</div>
          </div>
        )}

        {/* 1. Trip count slider + 100% toggle */}
        <div className="space-y-2 border border-outline-variant/60 rounded-lg p-3 bg-surface-container-lowest">
          <div className="flex items-center justify-between text-xs">
            <label htmlFor="preset-trip-slider" className="font-semibold">
              Số chuyến chạy:
            </label>
            <div className="flex items-center gap-2">
              <span className="font-mono font-bold text-primary" data-testid="selected-trip-count">
                {isFullRun ? `Toàn bộ (${totalAvailable})` : `${tripCount} / ${totalAvailable}`}
              </span>
              <label className="flex items-center gap-1.5 cursor-pointer select-none text-[11px] bg-surface-container px-2 py-0.5 rounded">
                <input
                  type="checkbox"
                  checked={isFullRun}
                  onChange={(e) => handleToggle100(e.target.checked)}
                  className="rounded border-outline-variant text-primary focus:ring-primary w-3 h-3"
                  aria-label="Chạy 100% toàn bộ chuyến"
                />
                <span className="font-semibold">100%</span>
              </label>
            </div>
          </div>

          <input
            id="preset-trip-slider"
            type="range"
            min={1}
            max={totalAvailable}
            step={1}
            value={tripCount}
            onChange={handleSliderChange}
            aria-label="Số chuyến chạy"
            className="w-full accent-primary cursor-pointer"
          />

          <div className="flex justify-between text-[10px] text-secondary">
            <span>1 chuyến</span>
            <span>{totalAvailable} chuyến</span>
          </div>
        </div>

        {/* 2. Rate: N trips every X seconds */}
        <div className="space-y-2 border border-outline-variant/60 rounded-lg p-3 bg-surface-container-lowest">
          <div className="text-xs font-semibold">Tốc độ phát hành trình (Rate limit)</div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="trips-per-batch-input" className="block text-[11px] text-secondary mb-1">
                Số chuyến mỗi đợt (N)
              </label>
              <input
                id="trips-per-batch-input"
                type="number"
                min={1}
                value={tripsPerBatch}
                onChange={(e) => setTripsPerBatch(Math.max(1, Number.parseInt(e.target.value, 10) || 1))}
                aria-label="Số chuyến mỗi đợt"
                className="w-full rounded border border-outline-variant/60 px-2 py-1 text-xs bg-white focus:outline-none focus:border-primary"
              />
            </div>
            <div>
              <label htmlFor="interval-seconds-input" className="block text-[11px] text-secondary mb-1">
                Khoảng cách giây (X)
              </label>
              <input
                id="interval-seconds-input"
                type="number"
                min={0.1}
                step={0.5}
                value={intervalS}
                onChange={(e) => setIntervalS(Math.max(0.1, Number.parseFloat(e.target.value) || 0.1))}
                aria-label="Khoảng cách giây"
                className="w-full rounded border border-outline-variant/60 px-2 py-1 text-xs bg-white focus:outline-none focus:border-primary"
              />
            </div>
          </div>
          <div className="text-[11px] text-secondary">
            Quy định: <span className="font-semibold text-on-surface">{tripsPerBatch} chuyến</span> mỗi{" "}
            <span className="font-semibold text-on-surface">{intervalS} giây</span>
          </div>
        </div>

        {/* 3. Driver checklist (Clerk linked drivers) */}
        <div className="border border-outline-variant/60 rounded-lg p-3 bg-surface-container-lowest">
          <div className="text-xs font-semibold mb-2">Tài xế thực hiện (Clerk linked)</div>
          <DriverChecklist
            drivers={drivers}
            selectedDriverIds={selectedDriverIds}
            onSelectionChange={setSelectedDriverIds}
            loading={driversLoading}
          />
        </div>

        <DialogFooter className="flex items-center justify-end gap-2 pt-2 border-t border-outline-variant/40">
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            disabled={isSubmitting}
            className="px-3 py-1.5 text-xs font-medium rounded border border-outline-variant/60 hover:bg-surface-container transition"
          >
            Hủy
          </button>
          <button
            type="button"
            onClick={handleStartRun}
            disabled={isRunDisabled}
            className="flex items-center gap-1.5 px-4 py-1.5 text-xs font-bold rounded bg-primary text-white hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition"
          >
            {isSubmitting ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Đang khởi tạo…</span>
              </>
            ) : (
              <>
                <Play className="w-3.5 h-3.5 fill-current" />
                <span>Bắt đầu chạy</span>
              </>
            )}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
