"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { CheckCircle2, XCircle, Send, Info, ArrowRight } from "lucide-react";
import type { ConfirmationChecklistItem } from "@/types/driver-blocks";

export interface ConfirmationCardProps {
  action: "acknowledge" | "submit_statement";
  checklist: ConfirmationChecklistItem[];
  summary: string;
  onConfirm?: () => void;
  onDecline?: () => void;
  pending?: boolean;
  className?: string;
}

const FALLBACK_LABELS: Record<string, string> = {
  confirmAcknowledgeTitle: "Confirm you accept the violation?",
  confirmAcknowledgeSummary: "Your acknowledgement is recorded and routed to a specialist.",
  confirmSubmitTitle: "Send this explanation for specialist review?",
  confirmSubmitSummary: "The case file is routed to Operations & Driver Support for review.",
  confirmIrreversibleNote: "Note: this action cannot be undone after sending.",
  confirmYes: "Yes, send now",
  confirmNo: "No, save draft",
  checklistHeader: "Your explanation",
  checklistValidBadge: "Valid",
  checklistIncidentType: "Incident type",
  checklistDescription: "Concrete description",
  checklistEvidence: "Verified evidence",
  checklistAcknowledgeDesc: "Confirm case details",
};

const CHECKLIST_KEY_MAP: Record<string, string> = {
  incident_type: "checklistIncidentType",
  description: "checklistDescription",
  evidence: "checklistEvidence",
};

function useSafeChatTranslate() {
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

export function ConfirmationCard({
  action,
  checklist,
  summary,
  onConfirm,
  onDecline,
  pending = false,
  className = "",
}: ConfirmationCardProps) {
  const tr = useSafeChatTranslate();

  const title =
    action === "acknowledge" ? tr("confirmAcknowledgeTitle") : tr("confirmSubmitTitle");
  const subtitle =
    action === "acknowledge" ? tr("confirmAcknowledgeSummary") : tr("confirmSubmitSummary");

  return (
    <div
      data-testid="driver-confirmation-card"
      className={`rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 shadow-md space-y-3 ${className}`}
    >
      {checklist && checklist.length > 0 && (
        <div className="bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-xl p-3 space-y-2">
          <div className="flex items-center justify-between border-b border-slate-200/70 dark:border-slate-700 pb-2">
            <span className="text-xs font-semibold text-emerald-700 dark:text-emerald-400">
              {tr("checklistHeader")}
            </span>
            <span className="px-2 py-0.5 bg-emerald-100 dark:bg-emerald-950/60 text-emerald-800 dark:text-emerald-300 rounded-full text-[11px] font-semibold">
              {tr("checklistValidBadge")}
            </span>
          </div>
          <ul className="space-y-1.5">
            {checklist.map((item) => {
              const mappedKey = CHECKLIST_KEY_MAP[item.key];
              const displayLabel = item.label || (mappedKey ? tr(mappedKey) : item.key);
              return (
                <li key={item.key} className="flex items-start gap-2 text-xs text-slate-800 dark:text-slate-200">
                  {item.ok ? (
                    <CheckCircle2
                      data-testid={`checklist-pass-${item.key}`}
                      className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5"
                    />
                  ) : (
                    <XCircle
                      data-testid={`checklist-fail-${item.key}`}
                      className="w-4 h-4 text-red-500 shrink-0 mt-0.5"
                    />
                  )}
                  <span>{displayLabel}</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-full bg-emerald-50 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-400 flex items-center justify-center shrink-0">
          <Send className="w-4 h-4" />
        </div>
        <div className="space-y-1">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100 leading-snug">
            {title}
          </h3>
          <p className="text-xs text-slate-700 dark:text-slate-300 font-medium">{summary}</p>
          <p className="text-[11px] text-slate-500 dark:text-slate-400">{subtitle}</p>
        </div>
      </div>

      <div className="bg-amber-50/80 dark:bg-amber-950/30 border border-amber-200/60 dark:border-amber-800/60 rounded-xl p-2.5 flex items-center gap-2">
        <Info className="w-4 h-4 text-amber-700 dark:text-amber-400 shrink-0" />
        <p className="text-[11px] text-amber-900 dark:text-amber-300 font-medium">
          {tr("confirmIrreversibleNote")}
        </p>
      </div>

      <div className="pt-1 space-y-2">
        <button
          type="button"
          data-testid="driver-confirm-yes"
          disabled={pending}
          onClick={() => onConfirm?.()}
          className="w-full h-11 bg-emerald-700 hover:bg-emerald-800 disabled:opacity-50 text-white font-semibold text-xs rounded-xl shadow-sm transition-all flex items-center justify-center gap-2 cursor-pointer"
        >
          <span>{tr("confirmYes")}</span>
          <ArrowRight className="w-4 h-4" />
        </button>
        <button
          type="button"
          data-testid="driver-confirm-no"
          disabled={pending}
          onClick={() => onDecline?.()}
          className="w-full h-10 bg-transparent hover:bg-slate-50 dark:hover:bg-slate-800 disabled:opacity-50 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300 font-semibold text-xs rounded-xl transition-all cursor-pointer"
        >
          {tr("confirmNo")}
        </button>
      </div>
    </div>
  );
}
