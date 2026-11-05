"use client";

import React from "react";
import type { EvidenceBlock, EvidenceItem, EvidenceKind } from "@/types/driver-blocks";
import {
  CloudRain,
  Car,
  MapPin,
  FileCheck,
  CheckCircle2,
} from "lucide-react";
import { type BlockLabels, resolveLabels } from "./labels";

export interface EvidenceBlockProps extends Omit<EvidenceBlock, "type"> {
  type?: "evidence";
  labels?: Partial<BlockLabels>;
  t?: Partial<BlockLabels>;
  className?: string;
}

function getEvidenceIcon(kind: EvidenceKind | string) {
  switch (kind) {
    case "weather":
      return CloudRain;
    case "traffic":
      return Car;
    case "telemetry":
      return MapPin;
    case "policy":
      return FileCheck;
    default:
      return CheckCircle2;
  }
}

export function EvidenceBlockComponent({
  items,
  labels,
  t,
  className = "",
}: EvidenceBlockProps) {
  if (!items || items.length === 0) return null;

  const l = resolveLabels(labels, t);

  return (
    <div
      className={`rounded-2xl border border-outline-variant/80 dark:border-slate-800 bg-surface-container-lowest dark:bg-slate-900/90 p-4 shadow-sm space-y-3 ${className}`}
    >
      <div className="flex items-center gap-2 pb-2.5 border-b border-outline-variant/40 dark:border-slate-800">
        <div className="w-7 h-7 rounded-lg bg-emerald-500/10 text-emerald-800 dark:text-emerald-400 flex items-center justify-center shrink-0">
          <FileCheck className="w-4 h-4 text-primary" />
        </div>
        <span className="font-bold text-sm text-on-surface dark:text-slate-100">
          {l.evidenceHeader}
        </span>
      </div>

      <div className="divide-y divide-outline-variant/30 dark:divide-slate-800 space-y-2.5 pt-1">
        {items.map((item: EvidenceItem, idx: number) => {
          const Icon = getEvidenceIcon(item.kind);
          const kindLabel = l.evidenceKinds[item.kind] || item.kind;

          return (
            <div key={idx} className="pt-2.5 first:pt-0 flex items-start gap-3">
              <div className="w-7 h-7 rounded-lg bg-surface-container dark:bg-slate-800 flex items-center justify-center text-primary dark:text-emerald-400 shrink-0 mt-0.5">
                <Icon className="w-4 h-4" />
              </div>

              <div className="flex-1 space-y-0.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold text-on-surface-variant dark:text-slate-300">
                    {kindLabel}
                  </span>
                  {item.source && (
                    <span className="text-[11px] text-on-surface-variant/80 dark:text-slate-400 italic">
                      {item.source}
                    </span>
                  )}
                </div>
                <p className="text-xs sm:text-sm text-on-surface dark:text-slate-100 font-medium leading-relaxed">
                  {item.summary}
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
