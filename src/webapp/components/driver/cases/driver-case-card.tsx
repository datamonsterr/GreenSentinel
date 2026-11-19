"use client";

import React from "react";
import { useRouter } from "next/navigation";
import { useTranslations, useLocale } from "next-intl";
import { Clock, Hourglass, ChevronRight } from "lucide-react";
import type { DriverCaseSessionItem } from "@/types/schemas";
import { formatShortCaseId, getStatusCopy, getViolationTitle } from "@/lib/driver/status-copy";
import { isResolvedCase } from "@/lib/driver/case-segments";
import { getTicketPhase, getTicketStep, TICKET_STEP_COUNT } from "@/lib/driver/tickets";

export interface DriverCaseCardProps {
  item: DriverCaseSessionItem;
  className?: string;
}

export function DriverCaseCard({ item, className = "" }: DriverCaseCardProps) {
  const router = useRouter();
  const t = useTranslations("driver");
  const locale = useLocale();

  const shortCode = formatShortCaseId(item.case_id);
  const displayTitle = getViolationTitle({
    code: item.violation_code,
    title: item.violation_title,
    locale,
  });
  const statusCopy = getStatusCopy(
    item.dispute_status || item.status,
    locale,
    item.dispute_status ? "dispute_status" : "status"
  );

  const resolved = isResolvedCase(item);
  const isUnderReview =
    item.dispute_status === "escalated" ||
    item.dispute_status === "in_dispute" ||
    item.dispute_status === "driver_disputed" ||
    item.dispute_status === "pending_review" ||
    item.dispute_status === "pending_analyst_review" ||
    item.status === "investigating" ||
    item.status === "in_review";

  // Status pill appearance
  let pillColor =
    "bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400 border-amber-200 dark:border-amber-800";
  

  if (resolved) {
    pillColor =
      "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800";
  } else if (isUnderReview) {
    pillColor =
      "bg-sky-50 dark:bg-sky-950/40 text-sky-700 dark:text-sky-400 border-sky-200 dark:border-sky-800";
  }

  // Relative / formatted time calculation.
  // Compares local CALENDAR dates (not raw millisecond deltas) so that e.g.
  // 23:50 yesterday viewed at 00:10 today correctly buckets as "Yesterday",
  // not "Today". An invalid/unparseable timestamp always falls back to
  // t("recent") and never renders "NaN".
  const timeSource = item.alleged_time || item.created_at;
  let formattedTime = t("recent");
  if (timeSource) {
    const date = new Date(timeSource);
    if (!Number.isNaN(date.getTime())) {
      const now = new Date();
      const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
      const diffCalendarDays = Math.round((startOfDay(now) - startOfDay(date)) / (1000 * 60 * 60 * 24));
      const timeStr = date.toLocaleTimeString(locale === "en" ? "en-US" : "vi-VN", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });

      if (diffCalendarDays <= 0) {
        formattedTime = t("cases.todayAt", { time: timeStr });
      } else if (diffCalendarDays === 1) {
        formattedTime = t("cases.yesterdayAt", { time: timeStr });
      } else if (diffCalendarDays > 1 && diffCalendarDays < 7) {
        formattedTime = t("cases.daysAgo", { count: diffCalendarDays });
      } else {
        formattedTime = date.toLocaleDateString(locale === "en" ? "en-US" : "vi-VN", {
          day: "2-digit",
          month: "2-digit",
        });
      }
    }
  }

  // Response deadline hint calculation.
  // An invalid/unparseable dispute_deadline (Number.isNaN(date.getTime()))
  // never renders a hint, and never renders "NaN".
  let deadlineHint: string | null = null;
  let deadlineUrgent = false;
  if (item.dispute_deadline && !resolved) {
    const deadlineDate = new Date(item.dispute_deadline);
    if (!Number.isNaN(deadlineDate.getTime())) {
      const remainingMs = deadlineDate.getTime() - new Date().getTime();
      if (remainingMs <= 0) {
        deadlineHint = t("cases.deadlinePassed");
        deadlineUrgent = true;
      } else {
        const remainingHours = remainingMs / (1000 * 60 * 60);
        if (remainingHours <= 24) {
          deadlineHint = t("cases.deadlineHours", { count: Math.max(1, Math.ceil(remainingHours)) });
          deadlineUrgent = true;
        } else {
          const remainingDays = Math.ceil(remainingHours / 24);
          deadlineHint = t("cases.deadlineDays", { count: remainingDays });
        }
      }
    }
  }

  const phase = getTicketPhase(item);
  const ticketStep = getTicketStep(item);
  const nextAction =
    phase === "closed"
      ? t("tickets.nextClosed")
      : phase === "pending"
        ? t("tickets.nextPending")
        : deadlineHint === t("cases.deadlinePassed")
          ? t("tickets.nextExpired")
          : t("tickets.nextOpen");

  const handleClick = () => {
    router.push(`/driver/chat/${encodeURIComponent(item.case_id)}`);
  };

  return (
    <article
      role="button"
      tabIndex={0}
      aria-label={t("cases.caseAria", {
        code: shortCode,
        title: displayTitle,
      })}
      onClick={handleClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          handleClick();
        }
      }}
      className={`relative overflow-hidden rounded-[20px] border border-slate-200/90 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 shadow-xs hover:border-emerald-500/70 hover:shadow-md transition-all active:scale-[0.99] cursor-pointer group select-none ${className}`}
    >
      {/* Accent left line */}

      {/* Top row: Short case ID & Natural status pill */}
      <div className="flex items-center justify-between gap-2 mb-2">
        <span
          className="font-mono text-xs font-bold px-2 py-0.5 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700"
          aria-label={t("cases.shortIdAria", { code: shortCode })}
        >
          {shortCode}
        </span>

        <span
          title={statusCopy.explanation}
          className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-semibold border ${pillColor}`}
        >
          {statusCopy.label}
        </span>
      </div>

      {/* Case title */}
      <h2 className="text-sm font-bold text-slate-900 dark:text-slate-100 group-hover:text-emerald-600 dark:group-hover:text-emerald-400 transition-colors leading-snug line-clamp-2">
        {displayTitle}
      </h2>

      {/* Ticket progress + next action */}
      <div className="mt-3" data-testid="ticket-progress">
        <div className="flex items-center gap-1" role="img" aria-label={t("tickets.stepOf", { current: ticketStep, total: TICKET_STEP_COUNT })}>
          {Array.from({ length: TICKET_STEP_COUNT }, (_, i) => (
            <span
              key={i}
              className={`h-1.5 flex-1 rounded-full ${i < ticketStep ? (resolved ? "bg-emerald-600" : "bg-emerald-600") : "bg-slate-200 dark:bg-slate-700"}`}
            />
          ))}
        </div>
        <div className="mt-1.5 flex items-center justify-between text-[11px] text-slate-500 dark:text-slate-400">
          <span className="font-semibold text-slate-600 dark:text-slate-300">{t(`tickets.step${ticketStep}`)}</span>
          <span>{t("tickets.stepOf", { current: ticketStep, total: TICKET_STEP_COUNT })}</span>
        </div>
        <p data-testid="ticket-next-action" className="mt-2 rounded-xl bg-[var(--driver-strip)] px-3 py-2 text-xs font-medium text-emerald-800 dark:text-emerald-300">
          {nextAction}
        </p>
      </div>

      {/* Bottom meta row: Relative time, deadline hint, chevron */}
      <div className="mt-3 pt-2.5 border-t border-slate-100 dark:border-slate-800/80 flex items-center justify-between text-xs">
        <div className="flex items-center space-x-2 text-slate-500 dark:text-slate-400">
          <span className="flex items-center">
            <Clock className="w-3.5 h-3.5 mr-1 shrink-0 text-slate-400 dark:text-slate-500" />
            <span>{formattedTime}</span>
          </span>

          {deadlineHint && (
            <>
              <span className="text-slate-300 dark:text-slate-700">•</span>
              <span
                className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border ${
                  deadlineUrgent
                    ? "bg-amber-100/90 dark:bg-amber-950/70 text-amber-800 dark:text-amber-300 border-amber-300 dark:border-amber-700"
                    : "bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400 border-amber-200 dark:border-amber-800"
                }`}
              >
                <Hourglass className="w-3 h-3 mr-1 shrink-0" />
                <span>{deadlineHint}</span>
              </span>
            </>
          )}
        </div>

        <ChevronRight className="w-4 h-4 text-slate-400 dark:text-slate-500 group-hover:translate-x-0.5 group-hover:text-emerald-600 dark:group-hover:text-emerald-400 transition-all shrink-0" />
      </div>
    </article>
  );
}
