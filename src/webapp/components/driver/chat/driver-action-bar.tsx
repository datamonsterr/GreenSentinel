"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { CheckCircle2 } from "lucide-react";

export interface DriverActionBarProps {
  caseId: string;
  hidden?: boolean;
  onAccept: () => void;
  onReject: () => void;
  disabled?: boolean;
}

const FALLBACK_LABELS: Record<string, string> = {
  acceptViolation: "Accept violation",
  rejectExplain: "Reject & explain",
};

function useSafeActionTranslate() {
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

export function DriverActionBar({
  caseId,
  hidden = false,
  onAccept,
  onReject,
  disabled = false,
}: DriverActionBarProps) {
  const tr = useSafeActionTranslate();

  if (hidden || !caseId) {
    return null;
  }

  return (
    <div
      data-testid="driver-action-bar"
      className="w-full border-t border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-4 py-2.5"
    >
      <div className="grid grid-cols-2 gap-3">
        <button
          type="button"
          data-testid="driver-action-accept"
          disabled={disabled}
          onClick={onAccept}
          className="h-11 border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-100 hover:bg-slate-50 dark:hover:bg-slate-800 disabled:opacity-50 font-semibold text-xs rounded-xl flex items-center justify-center transition-all cursor-pointer"
        >
          {tr("acceptViolation")}
        </button>
        <button
          type="button"
          data-testid="driver-action-reject"
          disabled={disabled}
          onClick={onReject}
          className="h-11 bg-emerald-700 hover:bg-emerald-800 disabled:opacity-50 text-white font-semibold text-xs rounded-xl flex items-center justify-center gap-1.5 shadow-sm transition-all cursor-pointer"
        >
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>{tr("rejectExplain")}</span>
        </button>
      </div>
    </div>
  );
}
