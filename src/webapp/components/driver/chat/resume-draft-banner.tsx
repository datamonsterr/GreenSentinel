"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { FileText, X } from "lucide-react";

export interface DriverStatementDraft {
  reason?: string;
  summary?: string;
  action?: "acknowledge" | "submit_statement";
  [key: string]: unknown;
}

export interface ResumeDraftBannerProps {
  draft?: DriverStatementDraft | null;
  onResume?: (draft: DriverStatementDraft) => void;
  onDismiss?: () => void;
}

const FALLBACK_LABELS: Record<string, string> = {
  resumeDraft: "You have an unsent explanation draft",
  resumeDraftAction: "Resume explanation",
  dismissDraft: "Dismiss",
};

function useSafeDraftTranslate() {
  try {
    const t = useTranslations("driver.chat");
    return (key: string) => {
      try {
        return t(key as Parameters<typeof t>[0]);
      } catch {
        return FALLBACK_LABELS[key] || key;
      }
    };
  } catch {
    return (key: string) => FALLBACK_LABELS[key] || key;
  }
}

export function ResumeDraftBanner({ draft, onResume, onDismiss }: ResumeDraftBannerProps) {
  const tr = useSafeDraftTranslate();

  if (!draft) {
    return null;
  }

  const draftSummary = draft.summary || draft.reason || "";
  if (!draftSummary && Object.keys(draft).length === 0) {
    return null;
  }

  return (
    <div
      data-testid="driver-resume-draft-banner"
      className="mx-4 mt-3 rounded-xl border border-emerald-200 dark:border-emerald-900 bg-emerald-50/80 dark:bg-emerald-950/30 p-3 text-xs flex items-center justify-between gap-3"
    >
      <div className="flex items-start gap-2 min-w-0 flex-1">
        <FileText className="w-4 h-4 text-emerald-700 dark:text-emerald-400 shrink-0 mt-0.5" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-emerald-900 dark:text-emerald-300">
            {tr("resumeDraft")}
          </p>
          {draftSummary && (
            <p className="text-slate-600 dark:text-slate-400 truncate mt-0.5">{draftSummary}</p>
          )}
        </div>
      </div>
      <div className="flex items-center gap-1.5 shrink-0">
        <button
          type="button"
          data-testid="driver-resume-draft-btn"
          onClick={() => onResume?.(draft)}
          className="px-2.5 py-1.5 rounded-lg bg-emerald-700 hover:bg-emerald-800 text-white font-semibold text-[11px] transition-colors cursor-pointer"
        >
          {tr("resumeDraftAction")}
        </button>
        {onDismiss && (
          <button
            type="button"
            data-testid="driver-dismiss-draft-btn"
            aria-label={tr("dismissDraft")}
            onClick={onDismiss}
            className="p-1 rounded-lg text-slate-500 hover:bg-emerald-100 dark:hover:bg-emerald-900/50 transition-colors cursor-pointer"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
    </div>
  );
}

export const FindDraftBanner = ResumeDraftBanner;
