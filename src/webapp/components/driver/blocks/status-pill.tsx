"use client";

import React from "react";
import type { StatusPillBlock } from "@/types/driver-blocks";
import { type BlockLabels, resolveLabels, VI_LABELS } from "./labels";

export interface StatusPillProps extends Omit<StatusPillBlock, "type"> {
  type?: "status_pill";
  statusLabel?: (key: string) => string;
  labels?: Partial<BlockLabels>;
  t?: Partial<BlockLabels>;
  className?: string;
}

const DEFAULT_STATUS_MAP: Record<string, string> = {
  ...VI_LABELS.status,
};

export function defaultStatusLabel(key: string, labels?: BlockLabels): string {
  if (labels?.status?.[key]) {
    return labels.status[key];
  }
  if (DEFAULT_STATUS_MAP[key]) {
    return DEFAULT_STATUS_MAP[key];
  }
  return key
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function StatusPill({
  status_key,
  statusLabel,
  labels,
  t,
  className = "",
}: StatusPillProps) {
  if (!status_key || !status_key.trim()) {
    return null;
  }

  const l = resolveLabels(labels, t);
  const label = statusLabel
    ? statusLabel(status_key)
    : defaultStatusLabel(status_key, l);

  const normalized = status_key.toLowerCase();
  const isEmerald =
    normalized.includes("resolv") ||
    normalized.includes("dismiss") ||
    normalized.includes("approv") ||
    normalized === "closed";
  const isAmber =
    normalized.includes("investigat") ||
    normalized.includes("pending") ||
    normalized.includes("review") ||
    normalized.includes("under_review") ||
    normalized.includes("submitted") ||
    normalized === "open";
  const isRose =
    normalized.includes("violation") ||
    normalized.includes("reject") ||
    normalized.includes("escalat") ||
    normalized.includes("sanction");

  const colorStyles = isEmerald
    ? "bg-emerald-500/10 text-emerald-800 dark:text-emerald-300 border-emerald-500/30"
    : isAmber
    ? "bg-amber-500/10 text-amber-800 dark:text-amber-300 border-amber-500/30"
    : isRose
    ? "bg-rose-500/10 text-rose-800 dark:text-rose-300 border-rose-500/30"
    : "bg-slate-500/10 text-slate-800 dark:text-slate-300 border-slate-500/30";

  const dotColor = isEmerald
    ? "bg-emerald-500"
    : isAmber
    ? "bg-amber-500"
    : isRose
    ? "bg-rose-500"
    : "bg-slate-400";

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold border ${colorStyles} ${className}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${dotColor} ${isAmber ? "animate-pulse" : ""}`} />
      <span>{label}</span>
    </span>
  );
}
