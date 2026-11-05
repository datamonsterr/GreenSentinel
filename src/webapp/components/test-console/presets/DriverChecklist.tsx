"use client";

import React from "react";
import type { ClerkLinkedDriver } from "@/lib/testApiClient";
import { Loader2 } from "lucide-react";

export interface DriverChecklistProps {
  drivers: ClerkLinkedDriver[];
  selectedDriverIds: string[];
  onSelectionChange: (driverIds: string[]) => void;
  loading?: boolean;
}

export function DriverChecklist({
  drivers,
  selectedDriverIds,
  onSelectionChange,
  loading = false,
}: DriverChecklistProps) {
  const allSelected = drivers.length > 0 && selectedDriverIds.length === drivers.length;

  const handleToggleAll = () => {
    if (allSelected) {
      onSelectionChange([]);
    } else {
      onSelectionChange(drivers.map((d) => d.driver_id));
    }
  };

  const handleToggleDriver = (driverId: string) => {
    if (selectedDriverIds.includes(driverId)) {
      onSelectionChange(selectedDriverIds.filter((id) => id !== driverId));
    } else {
      onSelectionChange([...selectedDriverIds, driverId]);
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs">
        <label className="flex items-center gap-2 font-medium cursor-pointer select-none">
          <input
            type="checkbox"
            checked={allSelected}
            onChange={handleToggleAll}
            disabled={loading || drivers.length === 0}
            className="rounded border-outline-variant text-primary focus:ring-primary w-3.5 h-3.5"
            aria-label="Chọn tất cả tài xế"
          />
          <span>Chọn tất cả</span>
        </label>
        <span className="text-secondary text-[11px]" data-testid="driver-selected-count">
          Đã chọn: {selectedDriverIds.length} / {drivers.length} tài xế
        </span>
      </div>

      <div
        className="max-h-40 overflow-y-auto border border-outline-variant/60 rounded-md p-2 space-y-1.5 bg-surface-container-lowest"
        data-testid="driver-checklist-scroll"
      >
        {loading ? (
          <div className="flex items-center justify-center py-4 text-xs text-secondary gap-2">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            <span>Đang tải danh sách tài xế…</span>
          </div>
        ) : drivers.length === 0 ? (
          <div className="text-center py-4 text-xs text-secondary">
            Không tìm thấy tài xế Clerk liên kết nào trong tổ chức.
          </div>
        ) : (
          drivers.map((drv) => {
            const isChecked = selectedDriverIds.includes(drv.driver_id);
            return (
              <label
                key={drv.driver_id}
                className={`flex items-center justify-between gap-2 p-1.5 rounded cursor-pointer transition text-xs select-none ${
                  isChecked ? "bg-primary/5 border border-primary/20" : "hover:bg-surface-container-low"
                }`}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <input
                    type="checkbox"
                    checked={isChecked}
                    onChange={() => handleToggleDriver(drv.driver_id)}
                    className="rounded border-outline-variant text-primary focus:ring-primary w-3.5 h-3.5"
                  />
                  <div className="min-w-0">
                    <div className="font-medium truncate">{drv.display_name}</div>
                    <div className="text-[10px] text-secondary truncate">{drv.email}</div>
                  </div>
                </div>
                {drv.license_plate && (
                  <span className="shrink-0 font-mono text-[10px] px-1.5 py-0.5 rounded bg-surface-container text-on-surface">
                    {drv.license_plate}
                  </span>
                )}
              </label>
            );
          })
        )}
      </div>

      <p className="text-[11px] text-secondary italic">
        * Các chuyến sẽ được phân bổ đều xoay vòng (round-robin) cho các tài xế đã chọn.
      </p>
    </div>
  );
}
