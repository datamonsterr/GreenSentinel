"use client";

import React from "react";
import { MapPin, Trash2, ArrowUp, ArrowDown } from "lucide-react";
import type { RouteWaypoint } from "@/lib/testApiClient";

export interface WaypointItem extends RouteWaypoint {
  id: string;
}

export interface WaypointPanelProps {
  waypoints: WaypointItem[];
  isClickMode: boolean;
  onToggleClickMode: () => void;
  onUpdateWaypointLeg: (id: string, leg: "pickup" | "destination") => void;
  onRemoveWaypoint: (id: string) => void;
  onMoveWaypoint: (id: string, direction: "up" | "down") => void;
  disabled?: boolean;
}

export function WaypointPanel({
  waypoints,
  isClickMode,
  onToggleClickMode,
  onUpdateWaypointLeg,
  onRemoveWaypoint,
  onMoveWaypoint,
  disabled = false,
}: WaypointPanelProps) {
  return (
    <div className="space-y-2 border-t border-outline-variant/40 pt-2.5">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-bold text-secondary uppercase tracking-wider">
          Điểm rẽ tùy ý ({waypoints.length})
        </span>
      </div>

      <button
        type="button"
        disabled={disabled}
        onClick={onToggleClickMode}
        aria-pressed={isClickMode}
        aria-label="Bật chế độ nhấp bản đồ để thêm điểm rẽ"
        className={`w-full py-1.5 px-2.5 rounded text-xs font-semibold border transition flex items-center justify-center gap-1.5 cursor-pointer shadow-xs ${
          isClickMode
            ? "bg-amber-500 text-white border-amber-600 animate-pulse"
            : disabled
            ? "bg-slate-100 text-slate-400 border-slate-200 cursor-not-allowed"
            : "bg-amber-50 hover:bg-amber-100 text-amber-900 border-amber-300"
        }`}
      >
        <MapPin className="w-3.5 h-3.5 shrink-0" />
        <span>
          {isClickMode
            ? "Đang bật: Nhấp trên bản đồ để thêm điểm (Bấm để tắt)"
            : "Thêm điểm rẽ (Nhấp trên bản đồ)"}
        </span>
      </button>

      {waypoints.length === 0 ? (
        <p className="text-[11px] text-slate-500 italic py-1">
          Chưa có điểm rẽ nào. Bật chế độ thêm điểm và nhấp trên bản đồ để chỉ định lộ trình tùy ý.
        </p>
      ) : (
        <ul className="space-y-1.5" aria-label="Danh sách điểm rẽ">
          {waypoints.map((wp, idx) => {
            const isFirst = idx === 0;
            const isLast = idx === waypoints.length - 1;
            return (
              <li
                key={wp.id}
                data-testid={`waypoint-item-${idx + 1}`}
                className="flex items-center justify-between gap-1.5 p-1.5 bg-white border border-outline-variant/60 rounded text-xs"
              >
                <div className="flex items-center gap-1.5 min-w-0 flex-1">
                  <span
                    data-testid={`waypoint-badge-${idx + 1}`}
                    className="w-4 h-4 rounded-full bg-amber-500 text-white font-bold text-[10px] flex items-center justify-center shrink-0"
                  >
                    {idx + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="font-semibold text-[11px] truncate">
                      {wp.name || `Điểm rẽ #${idx + 1}`}
                    </div>
                    <div className="text-[9px] font-mono text-slate-400">
                      [{wp.lat.toFixed(4)}, {wp.lon.toFixed(4)}]
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-1 shrink-0">
                  <select
                    value={wp.leg}
                    disabled={disabled}
                    aria-label={`Chặng của điểm rẽ ${idx + 1}`}
                    onChange={(e) =>
                      onUpdateWaypointLeg(wp.id, e.target.value as "pickup" | "destination")
                    }
                    className="h-6 px-1.5 text-[10px] rounded border border-slate-300 bg-white text-slate-700 focus:outline-none focus:border-primary disabled:opacity-50"
                  >
                    <option value="pickup">Chặng đón</option>
                    <option value="destination">Chặng trả</option>
                  </select>

                  <div className="flex items-center">
                    <button
                      type="button"
                      disabled={disabled || isFirst}
                      onClick={() => onMoveWaypoint(wp.id, "up")}
                      aria-label="Di chuyển điểm rẽ lên"
                      title="Di chuyển lên"
                      className="p-1 text-slate-500 hover:text-primary disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
                    >
                      <ArrowUp className="w-3 h-3" />
                    </button>
                    <button
                      type="button"
                      disabled={disabled || isLast}
                      onClick={() => onMoveWaypoint(wp.id, "down")}
                      aria-label="Di chuyển điểm rẽ xuống"
                      title="Di chuyển xuống"
                      className="p-1 text-slate-500 hover:text-primary disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
                    >
                      <ArrowDown className="w-3 h-3" />
                    </button>
                  </div>

                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => onRemoveWaypoint(wp.id)}
                    aria-label="Xóa điểm rẽ"
                    title="Xóa điểm rẽ"
                    className="p-1 text-slate-400 hover:text-error hover:bg-rose-50 rounded transition disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
