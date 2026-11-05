"use client";

import React from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { useLocale } from "@/lib/locale";
import { IconTile, toneText, type Tone } from "./icon-tile";
import { cockpitMessages } from "./messages";

export interface MetricCardProps {
  icon: LucideIcon;
  label: string;
  /** Formatted value; null renders the designed empty value. */
  value: React.ReactNode | null;
  /** Tile tint; defaults to the severity tone, else neutral. */
  tone?: Tone;
  /** Colors the value; set only when the measurement is flagged. */
  severity?: Exclude<Tone, "neutral" | "info" | "violet">;
  /** Explanation shown on hover (progressive disclosure). */
  hint?: string;
  /** "number" (default): large figure. "text": compact semibold, wraps to 2 lines, full value in the tooltip. */
  variant?: "number" | "text";
  children?: React.ReactNode;
  className?: string;
}

/** Icon tile LEFT, large value with muted label RIGHT. */
export function MetricCard({ icon, label, value, tone, severity, hint, variant = "number", children, className }: MetricCardProps) {
  const { locale } = useLocale();
  const empty = value === null || value === undefined || value === "";
  const shown = empty ? cockpitMessages[locale].noData : value;
  const name = `${label}: ${typeof shown === "string" || typeof shown === "number" ? shown : ""}`.replace(/: $/, "");
  return (
    <div role="group" aria-label={name} title={hint} className={cn("flex h-full min-w-0 items-center gap-3 rounded-lg border border-slate-200 bg-white p-3 shadow-xs", className)}>
      <IconTile icon={icon} tone={tone ?? severity ?? "neutral"} />
      <div className="min-w-0 flex-1">
        <div title={typeof shown === "string" ? shown : undefined} className={cn(
          empty
            ? "truncate text-sm font-medium text-slate-500"
            : variant === "text"
              ? cn("line-clamp-2 break-words text-[15px] font-semibold leading-snug", severity ? toneText[severity] : "text-slate-900")
              : cn("truncate tabular-nums text-2xl font-bold leading-tight tracking-tight", severity ? toneText[severity] : "text-slate-900"),
        )}>
          {shown}
        </div>
        <div className="mt-0.5 text-[13px] leading-snug text-slate-500">{label}</div>
        {children}
      </div>
    </div>
  );
}
