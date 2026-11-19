"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { Bot, CalendarClock, ChevronLeft } from "lucide-react";

/** Teal GSupport bot avatar (journey "Green Assistant" look). */
export function BotAvatar({ size = 32 }: { size?: number }) {
  return (
    <span
      aria-hidden="true"
      data-testid="driver-bot-avatar"
      style={{ width: size, height: size }}
      className="inline-flex shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-emerald-500 to-emerald-700 text-white"
    >
      <Bot style={{ width: size * 0.56, height: size * 0.56 }} />
    </span>
  );
}

export function ChatHeader({
  onBack,
  backLabel,
  title,
  subtitle,
  statusLabel,
  statusExplanation,
}: {
  onBack?: () => void;
  backLabel?: string;
  title: string;
  subtitle: string;
  statusLabel?: string | null;
  statusExplanation?: string;
}) {
  return (
    <div data-testid="driver-chat-header" className="flex items-center gap-2.5 px-3 py-2.5 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800">
      {onBack && (
        <button
          type="button"
          data-testid="case-back-button"
          aria-label={backLabel}
          title={backLabel}
          onClick={onBack}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-slate-700 hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800 -ml-1"
        >
          <ChevronLeft className="h-6 w-6" aria-hidden="true" />
        </button>
      )}
      <BotAvatar size={40} />
      <div className="min-w-0 flex-1">
        <div className="text-[15px] font-bold leading-tight truncate">{title}</div>
        <div className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400 truncate">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 shrink-0" />
          <span className="min-w-0 truncate">{subtitle}</span>
        </div>
      </div>
      {statusLabel && (
        <span
          data-testid="case-status-pill"
          title={statusExplanation}
          className="ml-auto px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[var(--driver-strip)] text-emerald-800 dark:text-emerald-300 whitespace-nowrap shrink-0"
        >
          {statusLabel}
        </span>
      )}
    </div>
  );
}

export function TypingBubble({ label }: { label: string }) {
  return (
    <div role="status" aria-label={label} className="flex items-end gap-2">
      <BotAvatar size={28} />
      <div className="flex items-center gap-1 rounded-2xl rounded-bl-md bg-white dark:bg-slate-800 px-4 py-3 shadow-xs">
        {[0, 1, 2].map((i) => (
          <span key={i} className="driver-typing-dot h-1.5 w-1.5 rounded-full bg-slate-400" />
        ))}
        <span className="sr-only">{label}</span>
      </div>
    </div>
  );
}

export function MsgTime({ date, align = "left" }: { date?: Date; align?: "left" | "right" }) {
  if (!date) return null;
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  return (
    <time
      dateTime={date.toISOString()}
      data-testid="driver-msg-time"
      className={`block text-[10px] text-slate-400 mt-0.5 ${align === "right" ? "text-right" : "text-left"}`}
    >
      {hh}:{mm}
    </time>
  );
}

export function QuickReplies({
  items,
  onPick,
  disabled,
}: {
  items: { key: string; label: string }[];
  onPick: (key: string) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("driver.chat");
  return (
    <div
      data-testid="driver-quick-replies"
      role="group"
      aria-label={t("quickRepliesLabel")}
      className="flex gap-2 overflow-x-auto px-3 pb-2 pt-1"
    >
      {items.map((it) => (
        <button
          key={it.key}
          type="button"
          disabled={disabled}
          onClick={() => onPick(it.key)}
          className="shrink-0 min-h-10 rounded-full border border-emerald-600/40 bg-white dark:bg-slate-900 px-4 text-[13px] font-semibold text-emerald-700 dark:text-emerald-300 active:scale-95 disabled:opacity-50 cursor-pointer"
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}

export function CaseSummaryCard({
  code,
  statusLabel,
  deadline,
}: {
  code: string;
  statusLabel?: string | null;
  deadline?: string | null;
}) {
  const t = useTranslations("driver.chat");
  let deadlineText: string | null = null;
  if (deadline) {
    const d = new Date(deadline);
    if (!Number.isNaN(d.getTime())) {
      deadlineText = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}, ${d.toLocaleDateString("vi-VN")}`;
    }
  }
  return (
    <div data-testid="driver-case-summary" className="rounded-[20px] bg-white dark:bg-slate-800 p-4 shadow-xs border border-slate-100 dark:border-slate-700 space-y-2.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-bold uppercase tracking-wide text-slate-500">{t("summaryTitle")}</span>
        <span className="font-mono text-xs font-bold px-2 py-0.5 rounded-md bg-slate-100 dark:bg-slate-700">{code}</span>
      </div>
      <dl className="text-xs space-y-1.5">
        {statusLabel && (
          <div className="flex justify-between gap-2">
            <dt className="text-slate-500">{t("summaryStatus")}</dt>
            <dd className="font-semibold">{statusLabel}</dd>
          </div>
        )}
        {deadlineText && (
          <div className="flex justify-between gap-2">
            <dt className="text-slate-500 flex items-center gap-1"><CalendarClock className="h-3.5 w-3.5" />{t("summaryDeadline")}</dt>
            <dd className="font-semibold">{deadlineText}</dd>
          </div>
        )}
      </dl>
    </div>
  );
}
