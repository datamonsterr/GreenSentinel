"use client";

import React from "react";
import type { LinkBlock } from "@/types/driver-blocks";
import { FileText, ArrowRight, ExternalLink } from "lucide-react";
import { isInternalScheme } from "./clickable-list";
import { type BlockLabels, resolveLabels } from "./labels";

export interface LinkBlockProps extends Omit<LinkBlock, "type"> {
  type?: "link";
  onNavigate?: (href: string) => void;
  labels?: Partial<BlockLabels>;
  t?: Partial<BlockLabels>;
  className?: string;
}

export function LinkBlockComponent({
  label,
  url,
  onNavigate,
  labels,
  t,
  className = "",
}: LinkBlockProps) {
  const l = resolveLabels(labels, t);
  const isInternal = isInternalScheme(url);
  const isExternal = url.startsWith("https://");

  if (isInternal) {
    return (
      <button
        type="button"
        onClick={() => onNavigate?.(url)}
        className={`w-full bg-surface-container-lowest dark:bg-slate-900/90 border border-outline-variant/80 dark:border-slate-800 hover:border-primary/80 dark:hover:border-emerald-500/80 active:scale-[0.99] transition-all rounded-2xl p-3.5 shadow-sm cursor-pointer flex items-center justify-between text-left group ${className}`}
      >
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-surface-container dark:bg-slate-800 flex items-center justify-center text-primary dark:text-emerald-400 shrink-0">
            <FileText className="w-5 h-5" />
          </div>
          <div>
            <p className="font-semibold text-sm text-on-surface dark:text-slate-100 group-hover:text-primary dark:group-hover:text-emerald-400 transition-colors">
              {label}
            </p>
            <p className="text-xs text-on-surface-variant dark:text-slate-400">
              {l.inAppNavigation}
            </p>
          </div>
        </div>
        <ArrowRight className="w-5 h-5 text-on-surface-variant dark:text-slate-400 group-hover:translate-x-0.5 group-hover:text-primary dark:group-hover:text-emerald-400 transition-all shrink-0" />
      </button>
    );
  }

  if (isExternal) {
    return (
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className={`w-full bg-surface-container-lowest dark:bg-slate-900/90 border border-outline-variant/80 dark:border-slate-800 hover:border-primary/80 dark:hover:border-emerald-500/80 active:scale-[0.99] transition-all rounded-2xl p-3.5 shadow-sm cursor-pointer flex items-center justify-between text-left group ${className}`}
      >
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-surface-container dark:bg-slate-800 flex items-center justify-center text-primary dark:text-emerald-400 shrink-0">
            <FileText className="w-5 h-5" />
          </div>
          <div>
            <p className="font-semibold text-sm text-on-surface dark:text-slate-100 group-hover:text-primary dark:group-hover:text-emerald-400 transition-colors">
              {label}
            </p>
            <p className="text-xs text-on-surface-variant dark:text-slate-400 truncate max-w-[220px]">
              {url}
            </p>
          </div>
        </div>
        <ExternalLink className="w-5 h-5 text-on-surface-variant dark:text-slate-400 group-hover:text-primary dark:group-hover:text-emerald-400 transition-all shrink-0" />
      </a>
    );
  }

  // Scheme not in allowlist: render as plain text without button or link
  return (
    <div
      className={`w-full bg-surface-container-lowest dark:bg-slate-900/90 border border-outline-variant/80 dark:border-slate-800 rounded-2xl p-3.5 shadow-sm text-left ${className}`}
    >
      <span className="font-semibold text-sm text-on-surface dark:text-slate-100">
        {label}
      </span>
    </div>
  );
}
