"use client";

import React from "react";
import type { TripCardBlock } from "@/types/driver-blocks";
import { Car, ChevronRight } from "lucide-react";
import { type BlockLabels, resolveLabels } from "./labels";

export interface TripCardProps extends Omit<TripCardBlock, "type"> {
  type?: "trip_card";
  onNavigate?: (href: string) => void;
  labels?: Partial<BlockLabels>;
  t?: Partial<BlockLabels>;
  className?: string;
}

export function formatTripId(tripId: string): string {
  if (!tripId) return "#GS-TRIP";
  const clean = tripId.replace(/^(trip[-_]?|#)/i, "");
  const match = clean.match(/^(?:GS-)?([a-zA-Z0-9]{4,6})/i);
  if (match) {
    return `#GS-${match[1].toUpperCase()}`;
  }
  const alphanum = clean.replace(/[^a-zA-Z0-9]/g, "");
  return `#GS-${(alphanum.slice(0, 5) || "TRIP").toUpperCase()}`;
}

export function formatVnd(amount: number): string {
  if (amount === undefined || amount === null || Number.isNaN(amount)) {
    return "";
  }
  return `${new Intl.NumberFormat("vi-VN").format(amount)} ₫`;
}

export function TripCard({
  trip_id,
  pickup,
  destination,
  fare_vnd,
  onNavigate,
  labels,
  t,
  className = "",
}: TripCardProps) {
  const l = resolveLabels(labels, t);
  const hasFare = fare_vnd !== undefined && fare_vnd !== null && !Number.isNaN(fare_vnd);

  const handleClick = () => {
    onNavigate?.(`trip://${trip_id}`);
  };

  return (
    <div
      className={`rounded-2xl border border-outline-variant/80 dark:border-slate-800 bg-surface-container-lowest dark:bg-slate-900/90 p-4 shadow-sm space-y-3.5 ${className}`}
    >
      {/* Header: Never expose trip_id fragment, show opaque localized label */}
      <div className="flex items-center justify-between pb-2.5 border-b border-outline-variant/40 dark:border-slate-800">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-xl bg-primary/10 text-primary dark:text-emerald-400 flex items-center justify-center shrink-0">
            <Car className="w-4 h-4 text-primary" />
          </div>
          <span className="font-bold text-sm text-on-surface dark:text-slate-100">
            {l.trip}
          </span>
        </div>
      </div>

      {/* Route Flow */}
      <div className="relative pl-6 space-y-3">
        {/* Connecting Line */}
        <div className="absolute left-2 top-2.5 bottom-2.5 w-0.5 border-l-2 border-dashed border-outline-variant/60 dark:border-slate-700" />

        {/* Pickup */}
        <div className="relative flex items-start">
          <div className="absolute -left-6 top-1 w-4 h-4 rounded-full bg-primary flex items-center justify-center">
            <div className="w-1.5 h-1.5 rounded-full bg-on-primary" />
          </div>
          <div>
            <span className="text-[11px] font-semibold text-on-surface-variant dark:text-slate-400 uppercase tracking-wider block">
              {l.pickup}
            </span>
            <p className="text-sm font-medium text-on-surface dark:text-slate-100">{pickup}</p>
          </div>
        </div>

        {/* Destination */}
        <div className="relative flex items-start">
          <div className="absolute -left-6 top-1 w-4 h-4 rounded bg-emerald-700 dark:bg-emerald-600 flex items-center justify-center">
            <div className="w-1.5 h-1.5 rounded-xs bg-white" />
          </div>
          <div>
            <span className="text-[11px] font-semibold text-on-surface-variant dark:text-slate-400 uppercase tracking-wider block">
              {l.destination}
            </span>
            <p className="text-sm font-medium text-on-surface dark:text-slate-100">
              {destination}
            </p>
          </div>
        </div>
      </div>

      {/* Fare and Action Grid: Hide fare row completely when missing */}
      <div
        className={`pt-2 border-t border-outline-variant/40 dark:border-slate-800 items-center ${
          hasFare ? "grid grid-cols-2 gap-2" : "flex justify-end"
        }`}
      >
        {hasFare && (
          <div className="bg-surface-container-low dark:bg-slate-800/60 p-2.5 rounded-xl">
            <span className="text-[11px] font-semibold text-on-surface-variant dark:text-slate-400 block">
              {l.fareRecorded}
            </span>
            <span className="text-sm font-bold text-primary dark:text-emerald-400 mt-0.5 block">
              {formatVnd(fare_vnd)}
            </span>
          </div>
        )}

        <button
          type="button"
          onClick={handleClick}
          aria-label={l.tripDetails}
          className={`${
            hasFare ? "h-full min-h-[48px]" : "py-2 px-4 min-h-[40px]"
          } bg-emerald-500/10 hover:bg-emerald-500/20 text-primary dark:text-emerald-300 font-semibold text-xs rounded-xl flex items-center justify-center gap-1 active:scale-95 transition-all cursor-pointer`}
        >
          <span>{l.tripDetails}</span>
          <ChevronRight className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}
