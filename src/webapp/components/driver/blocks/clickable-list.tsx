"use client";

import React from "react";
import type { ClickableListBlock } from "@/types/driver-blocks";
import { ChevronRight, ExternalLink } from "lucide-react";
import { type BlockLabels } from "./labels";

export interface ClickableListProps extends Omit<ClickableListBlock, "type"> {
  type?: "list";
  onNavigate?: (href: string) => void;
  labels?: Partial<BlockLabels>;
  t?: Partial<BlockLabels>;
  className?: string;
}

export const ALLOWED_INTERNAL_SCHEMES = ["case://", "trip://", "policy://"] as const;

export function isInternalScheme(href: string): boolean {
  if (!href) return false;
  return ALLOWED_INTERNAL_SCHEMES.some((scheme) => href.startsWith(scheme));
}

export function isAllowedScheme(href: string): boolean {
  if (!href) return false;
  return isInternalScheme(href) || href.startsWith("https://");
}

export function ClickableList({ items, onNavigate, className = "" }: ClickableListProps) {
  if (!items || items.length === 0) return null;

  return (
    <div
      className={`rounded-2xl border border-outline-variant/80 dark:border-slate-800 bg-surface-container-lowest dark:bg-slate-900/90 shadow-sm divide-y divide-outline-variant/40 dark:divide-slate-800 overflow-hidden ${className}`}
    >
      {items.map((item, idx) => {
        const isInternal = isInternalScheme(item.href);
        const isExternal = item.href.startsWith("https://");

        if (isInternal) {
          return (
            <button
              key={idx}
              type="button"
              onClick={() => onNavigate?.(item.href)}
              className="w-full py-3 px-4 flex items-center justify-between text-left hover:bg-surface-container-low dark:hover:bg-slate-800/60 active:scale-[0.99] transition-all cursor-pointer group"
            >
              <span className="text-sm font-medium text-on-surface dark:text-slate-200 group-hover:text-primary dark:group-hover:text-emerald-400 transition-colors">
                {item.label}
              </span>
              <ChevronRight className="w-4 h-4 text-on-surface-variant dark:text-slate-400 group-hover:translate-x-0.5 group-hover:text-primary dark:group-hover:text-emerald-400 transition-all shrink-0" />
            </button>
          );
        }

        if (isExternal) {
          return (
            <a
              key={idx}
              href={item.href}
              target="_blank"
              rel="noopener noreferrer"
              className="w-full py-3 px-4 flex items-center justify-between text-left hover:bg-surface-container-low dark:hover:bg-slate-800/60 active:scale-[0.99] transition-all cursor-pointer group"
            >
              <span className="text-sm font-medium text-on-surface dark:text-slate-200 group-hover:text-primary dark:group-hover:text-emerald-400 transition-colors">
                {item.label}
              </span>
              <ExternalLink className="w-4 h-4 text-on-surface-variant dark:text-slate-400 group-hover:text-primary dark:group-hover:text-emerald-400 transition-colors shrink-0" />
            </a>
          );
        }

        // Scheme not in allowlist: render as plain text without button or link
        return (
          <div
            key={idx}
            className="w-full py-3 px-4 flex items-center justify-between text-left"
          >
            <span className="text-sm font-medium text-on-surface dark:text-slate-200">
              {item.label}
            </span>
          </div>
        );
      })}
    </div>
  );
}
