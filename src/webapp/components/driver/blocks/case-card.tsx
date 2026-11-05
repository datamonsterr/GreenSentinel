"use client";

import React from "react";
import type { CaseCardBlock } from "@/types/driver-blocks";
import { StatusPill } from "./status-pill";
import { ShieldAlert, ChevronRight } from "lucide-react";
import { type BlockLabels, resolveLabels } from "./labels";

export interface CaseCardProps extends Omit<CaseCardBlock, "type"> {
  type?: "case_card";
  onNavigate?: (href: string) => void;
  statusLabel?: (key: string) => string;
  labels?: Partial<BlockLabels>;
  t?: Partial<BlockLabels>;
  className?: string;
}

export function formatCaseId(caseId: string): string {
  if (!caseId) return "#CASE";
  const clean = caseId.replace(/^(case[-_]?|#)/i, "");
  const shortHex = clean.replace(/[^a-zA-Z0-9]/g, "").slice(0, 4);
  return `#${(shortHex || clean.slice(0, 4)).toUpperCase()}`;
}

export function CaseCard({
  case_id,
  title,
  status_key,
  onNavigate,
  statusLabel,
  labels,
  t,
  className = "",
}: CaseCardProps) {
  const l = resolveLabels(labels, t);
  const shortCode = formatCaseId(case_id);

  const handleClick = () => {
    onNavigate?.(`case://${case_id}`);
  };

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`${l.casePrefix} ${shortCode}: ${title}`}
      onClick={handleClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          handleClick();
        }
      }}
      className={`group w-full text-left rounded-2xl border border-outline-variant/80 dark:border-slate-800 bg-surface-container-lowest dark:bg-slate-900/90 p-4 shadow-sm hover:border-primary/60 hover:shadow-md transition-all cursor-pointer select-none ${className}`}
    >
      <div className="flex items-center justify-between gap-2 pb-2.5 border-b border-outline-variant/40 dark:border-slate-800">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-xl bg-emerald-500/10 text-emerald-800 dark:text-emerald-400 flex items-center justify-center shrink-0">
            <ShieldAlert className="w-4 h-4 text-primary" />
          </div>
          <span className="font-bold text-sm tracking-wide text-primary dark:text-emerald-400">
            {shortCode}
          </span>
        </div>
        <StatusPill status_key={status_key} statusLabel={statusLabel} labels={labels} t={t} />
      </div>

      <div className="pt-3 flex items-center justify-between gap-3">
        <p className="font-semibold text-sm text-on-surface dark:text-slate-100 line-clamp-2">
          {title}
        </p>
        <ChevronRight className="w-4 h-4 text-on-surface-variant dark:text-slate-400 group-hover:translate-x-0.5 group-hover:text-primary transition-all shrink-0" />
      </div>
    </div>
  );
}
