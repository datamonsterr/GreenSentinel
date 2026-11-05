"use client";

import React from "react";
import type { NextStepsBlock, NextStepsItem } from "@/types/driver-blocks";
import { Sparkles, ArrowUpRight } from "lucide-react";
import { type BlockLabels, resolveLabels } from "./labels";

export interface NextStepsProps extends Omit<NextStepsBlock, "type"> {
  type?: "next_steps";
  onPrompt?: (prompt: string) => void;
  labels?: Partial<BlockLabels>;
  t?: Partial<BlockLabels>;
  className?: string;
}

export function NextSteps({
  items,
  onPrompt,
  labels,
  t,
  className = "",
}: NextStepsProps) {
  if (!items || items.length === 0) return null;

  const l = resolveLabels(labels, t);

  return (
    <div className={`space-y-2 pt-1 ${className}`}>
      <div className="flex items-center gap-1.5 text-xs font-semibold text-on-surface-variant dark:text-slate-400">
        <Sparkles className="w-3.5 h-3.5 text-primary dark:text-emerald-400" />
        <span>{l.nextStepsHeader}</span>
      </div>

      <div className="flex flex-wrap gap-2">
        {items.map((item: NextStepsItem, idx: number) => (
          <button
            key={idx}
            type="button"
            onClick={() => onPrompt?.(item.prompt)}
            className="group bg-surface-container-lowest dark:bg-slate-800/90 border border-outline-variant/80 dark:border-slate-700 text-on-surface dark:text-slate-200 font-medium text-xs sm:text-sm px-3.5 py-2 rounded-xl flex items-center gap-1.5 hover:border-primary/60 hover:bg-surface-container-low dark:hover:bg-slate-800 active:scale-95 transition-all cursor-pointer shadow-2xs"
          >
            <span>{item.label}</span>
            <ArrowUpRight className="w-3.5 h-3.5 text-on-surface-variant dark:text-slate-400 group-hover:text-primary dark:group-hover:text-emerald-400 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-all" />
          </button>
        ))}
      </div>
    </div>
  );
}
