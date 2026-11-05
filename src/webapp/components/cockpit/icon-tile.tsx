import React from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SignalTone } from "@/lib/cockpit-signals";

export type Tone = SignalTone;

export const toneTile: Record<Tone, string> = {
  neutral: "bg-slate-100 text-slate-600",
  success: "bg-emerald-50 text-emerald-700",
  warning: "bg-amber-50 text-amber-700",
  danger: "bg-red-50 text-red-700",
  info: "bg-sky-50 text-sky-700",
  violet: "bg-violet-50 text-violet-700",
};

export const toneText: Record<Tone, string> = {
  neutral: "text-slate-900",
  success: "text-emerald-700",
  warning: "text-amber-700",
  danger: "text-red-700",
  info: "text-sky-700",
  violet: "text-violet-700",
};

export const toneDot: Record<Tone, string> = {
  neutral: "bg-slate-400",
  success: "bg-emerald-600",
  warning: "bg-amber-500",
  danger: "bg-red-600",
  info: "bg-sky-600",
  violet: "bg-violet-600",
};

const sizes = {
  md: { tile: "size-11", glyph: 22 },
  lg: { tile: "size-12", glyph: 24 },
  sm: { tile: "size-9", glyph: 18 },
} as const;

/** Tinted square with the glyph optically centered (flex center, block svg, no baseline gap). */
export function IconTile({ icon: Icon, tone = "neutral", size = "md", className }: {
  icon: LucideIcon;
  tone?: Tone;
  size?: keyof typeof sizes;
  className?: string;
}) {
  const { tile, glyph } = sizes[size];
  return (
    <span aria-hidden="true" className={cn("inline-flex shrink-0 items-center justify-center rounded-xl leading-none", tile, toneTile[tone], className)}>
      <Icon size={glyph} strokeWidth={2} className="block shrink-0" />
    </span>
  );
}
