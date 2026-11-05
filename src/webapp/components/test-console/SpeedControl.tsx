"use client";

import React from "react";
import { Gauge } from "lucide-react";

export interface SpeedControlProps {
  value: number;
  onChange: (speedFactor: number) => void;
  disabled?: boolean;
  className?: string;
}

const PRESET_SPEEDS = [1, 2, 5, 10];

export function SpeedControl({
  value,
  onChange,
  disabled = false,
  className = "",
}: SpeedControlProps) {
  const currentVal = Math.max(1, Math.min(20, Math.round(value) || 1));

  return (
    <div
      data-testid="speed-control"
      className={`flex flex-col gap-1.5 p-2 bg-white border border-outline-variant/60 rounded ${className}`}
    >
      <div className="flex items-center justify-between text-xs">
        <span className="font-semibold text-slate-700 flex items-center gap-1">
          <Gauge className="w-3.5 h-3.5 text-primary" />
          <span>Tốc độ mô phỏng</span>
        </span>
        <span
          data-testid="speed-factor-display"
          className="font-bold text-primary font-mono text-xs px-1.5 py-0.5 bg-primary/10 rounded"
        >
          {currentVal}x
        </span>
      </div>

      <div className="flex items-center gap-2">
        <input
          type="range"
          min={1}
          max={20}
          step={1}
          value={currentVal}
          disabled={disabled}
          aria-label="Thanh trượt tốc độ mô phỏng"
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-full h-1.5 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-primary disabled:opacity-50 disabled:cursor-not-allowed"
        />
      </div>

      <div className="flex items-center justify-between gap-1 pt-0.5">
        <div className="flex items-center gap-1">
          {PRESET_SPEEDS.map((factor) => {
            const isActive = currentVal === factor;
            return (
              <button
                key={factor}
                type="button"
                disabled={disabled}
                onClick={() => onChange(factor)}
                aria-label={`Tốc độ ${factor}x`}
                className={`px-2 py-0.5 text-[11px] font-bold rounded border transition cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed ${
                  isActive
                    ? "bg-primary text-white border-primary shadow-2xs"
                    : "bg-surface-container-lowest text-secondary border-outline-variant/60 hover:bg-slate-50"
                }`}
              >
                {factor}x
              </button>
            );
          })}
        </div>
        <span className="text-[10px] text-slate-400 font-mono">1x - 20x</span>
      </div>
    </div>
  );
}
