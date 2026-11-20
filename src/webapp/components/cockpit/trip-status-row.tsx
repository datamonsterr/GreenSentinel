"use client";

import React from "react";
import { ArrowRight } from "lucide-react";
import type { CaseDetailResponse } from "@/types/schemas";
import { useLocale } from "@/lib/locale";
import { workspaceState } from "@/lib/workspace-messages";
import { cn } from "@/lib/utils";
import { CopyId } from "./copy-id";
import { cockpitMessages, numberLocale } from "./messages";

/** One line: dot, pickup → destination (adjacent, truncated), badges, fare, trip-ID chip. */
export function TripStatusRow({ caseDetail, onOpen, className }: { caseDetail: CaseDetailResponse; onOpen?: () => void; className?: string }) {
  const { locale } = useLocale();
  const t = cockpitMessages[locale];
  const trip = caseDetail.trip;
  const pickup = trip?.pickup_address || t.noData;
  const drop = trip?.dropoff_address || t.noData;
  const fare = typeof trip?.fare_amount_vnd === "number" && Number.isFinite(trip.fare_amount_vnd)
    ? `${trip.fare_amount_vnd.toLocaleString(numberLocale(locale))} ₫`
    : null;
  const name = `${pickup} → ${drop}`;
  const route = (
    <>
      <span aria-hidden="true" className="size-2.5 shrink-0 rounded-full border-2 border-gs-green" />
      <span className="min-w-0 truncate font-medium text-slate-900">{pickup}</span>
      <ArrowRight aria-hidden="true" size={14} className="block shrink-0 text-slate-400" />
      <span className="min-w-0 truncate font-medium text-slate-900">{drop}</span>
    </>
  );
  const routeClass = "flex min-w-0 max-w-[60%] items-center gap-1.5";
  return (
    <div data-testid="trip-status-row" className={cn("flex h-11 min-w-0 flex-nowrap items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-[13px] shadow-xs", className)}>
      {onOpen ? (
        <button type="button" title={name} aria-label={name} onClick={onOpen} className={cn(routeClass, "rounded text-left hover:text-gs-green-ink focus-visible:outline-gs-green")}>
          {route}
        </button>
      ) : (
        <div title={name} className={routeClass}>{route}</div>
      )}
      {trip?.driver_status && (
        <span title={t.driverStatus} className="shrink-0 rounded-full bg-primary px-2 py-0.5 text-[11px] font-semibold text-white">
          {workspaceState(trip.driver_status, locale)}
        </span>
      )}
      {trip?.match_type && (
        <span title={t.match} className="shrink-0 rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-medium text-slate-700">
          {workspaceState(trip.match_type, locale)}
        </span>
      )}
      <span className="ml-auto" aria-hidden="true" />
      {fare && (
        <span title={t.fare} className="shrink-0 text-sm font-bold tabular-nums text-slate-900">
          <span className="sr-only">{t.fare}: </span>{fare}
        </span>
      )}
      {trip?.id && <CopyId id={String(trip.id)} label={t.tripId} />}
    </div>
  );
}
