import React from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SignalTone } from "@/lib/cockpit-signals";

export type Tone = SignalTone;

export const toneTile: Record<Tone, string> = {
  neutral: "bg-slate-100 text-slate-600",
  success: "bg-gs-green-soft text-gs-green-ink",
  warning: "bg-gs-amber-soft text-gs-amber-ink",
  danger: "bg-gs-red-soft text-gs-red",
  info: "bg-gs-cyan-soft text-gs-cyan",
  violet: "bg-gs-purple-soft text-gs-purple",
};

export const toneText: Record<Tone, string> = {
  neutral: "text-slate-900",
  success: "text-gs-green-ink",
  warning: "text-gs-amber-ink",
  danger: "text-gs-red",
  info: "text-gs-cyan",
  violet: "text-gs-purple",
};

export const toneDot: Record<Tone, string> = {
  neutral: "bg-slate-400",
  success: "bg-primary",
  warning: "bg-gs-amber",
  danger: "bg-gs-red",
  info: "bg-gs-cyan",
  violet: "bg-gs-purple",
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
