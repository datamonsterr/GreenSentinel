import React from "react";
import { caseStatusLabel, caseStatusTone } from "@/lib/status-tone";
import type { Locale } from "@/lib/locale";

/** Status chip shared by queue, case header, Complete tab and the workflow stepper. */
export function CaseStatusChip({ status, locale, testId, className = "" }: { status?: string | null; locale: Locale; testId?: string; className?: string }) {
  if (!status) return <>—</>;
  return <span data-testid={testId} className={`gs-tone pill ${caseStatusTone(status)} ${className}`.trim()}>{caseStatusLabel(status, locale)}</span>;
}
